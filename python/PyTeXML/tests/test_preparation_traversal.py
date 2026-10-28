"""Multi-file tests through the production preparation entry point."""
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper
from src.prepare.session import PreparationUnresolved
from src.prepare.provenance import ProvenanceLedger
from src.event_log import read_events
from src.source_io import SourceStore


class TraversalTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def document(self, body, preamble="", name="main.tex"):
        return self.put(name, "\\documentclass{article}\n" + preamble +
                        "\n\\begin{document}\n" + body + "\n\\end{document}\n")

    def prepare(self, **kwargs):
        return preprocess_paper(str(self.root), **kwargs)

    def test_character_code_save_restore_allows_child_inlining_with_source_coverage(self):
        self.document(r"LEFT\input{defs}RIGHT")
        child = (r"\chardef\saved=\catcode`\@ " "\n"
                 r"\catcode`\@=11 " "\n"
                 r"\def\foo@bar{BODY}" "\n"
                 r"\catcode`\@=\saved " "\n")
        self.put("defs.tex", child)
        text, manifest, _, ledger = self.prepare()
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertEqual(manifest.unresolved, [])
        self.assertNotIn(r"\input", text)
        self.assertIn(r"\def\foo@bar{BODY}", text)
        self.assertIn(r"\catcode`\@=\saved", text)
        self.assertEqual(ledger.master_length, len(text))
        self.assertTrue(ledger.resolve_source_line("defs.tex", 1)["occurrences"])

    def test_code_value_control_word_remains_separated_when_comment_is_removed(self):
        self.document("\\chardef\\saved=12 \\catcode64=\\saved%comment\nTEXT")
        text, manifest, _, _ = self.prepare()
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertNotIn(r"\savedTEXT", text)
        self.assertIn(r"\saved TEXT", text)

    def test_number_lookahead_keeps_assignment_and_terminator_source_disjoint(self):
        self.document(r"{\catcode64=11@ @} @")
        text, manifest, _, ledger = self.prepare()
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertIn(r"\catcode64=11@ @", text)
        self.assertEqual(text.count("@"), 3)
        self.assertEqual(ledger.master_length, len(text))

    def test_stored_code_assignment_target_is_not_a_file_request(self):
        self.document(r"\def\later{\chardef\input=12 \input{not-a-file}}BODY")
        _, manifest, _, _ = self.prepare()
        self.assertFalse([r for r in manifest.requirements if r["reason"] == "deferred_dependency"])

    def test_nested_root_repeats_inline_prefix_suffix_and_one_read_per_file(self):
        self.document("LEFT\\input{sections/a}RIGHT\\input{sections/a}END", name="paper/root.tex")
        self.put("paper/sections/a.tex", "A\\input{sections/shared}Z")
        self.put("paper/sections/shared.tex", "SHARED")
        original = Path.read_bytes
        reads = Counter()
        def read(path):
            reads[path.resolve()] += 1
            return original(path)
        with patch.object(Path, "read_bytes", read):
            text, manifest, output, ledger = self.prepare()
        self.assertEqual(text.count("SHARED"), 2)
        self.assertIn("LEFTASHARED Z RIGHTASHARED Z END", text)
        self.assertNotIn("\\input", text)
        self.assertEqual([o["source"] for o in manifest.input_occurrences],
            ["paper/root.tex", "paper/sections/a.tex", "paper/sections/shared.tex",
             "paper/sections/a.tex", "paper/sections/shared.tex"])
        self.assertTrue(all(reads[self.root / p] == 1 for p in manifest.source_reads))
        self.assertEqual(ledger.master_length, len(text))
        self.assertEqual(ledger.summary()["total_master_lines"], len(text.splitlines()))
        records = ledger.resolve_source_line("paper/sections/shared.tex", 1)["occurrences"]
        self.assertEqual({s["occurrence"] for s in records}, {2, 4})
        self.assertGreater(len(ledger.resolve_master_line(1)["origins"]), 1)
        loaded = ProvenanceLedger.load(output / "master.provenance.json")
        self.assertEqual(loaded.to_dict(), ledger.to_dict())
        for segment in ledger.segments:
            if segment["operation"] == "IDENTITY":
                a, b = segment["generated"]
                c, d = segment["source"]
                self.assertEqual(text[a:b], (self.root / segment["source_file"]).read_text(encoding="utf-8")[c:d])

    def test_contexts_exclude_false_dependencies_without_damaging_source_bodies(self):
        definition = r"\def\later#1{\input{absent-definition}#1% keep" + "\n  BODY}"
        literal = "\\begin{verbatim}\n\\input{absent-literal}% untouched\n\\end{verbatim}"
        body = ("% \\input{absent-comment}\n" + definition + "\n" + literal +
                "\n\\iffalse \\input{absent-skipped}\\else \\input{live}\\fi")
        self.document(body)
        self.put("live.tex", "LIVE")
        self.put("dormant.tex", "DORMANT")
        text, manifest, _, _ = self.prepare(root_tex="main.tex")
        self.assertIn(definition, text)
        self.assertIn(literal, text)
        self.assertIn("LIVE", text)
        self.assertNotIn("absent-comment", text)
        self.assertNotIn("absent-skipped", text)
        self.assertEqual(manifest.active_tex_files, ["live.tex", "main.tex"])
        self.assertEqual(manifest.dormant_tex_files, ["dormant.tex"])
        self.assertEqual([e["target"] for e in manifest.dependencies], ["live.tex"])

    def test_primitive_input_endinput_finishes_line_and_resumes_parent(self):
        self.document("BEFORE\\input child AFTER")
        self.put("child.tex", "CHILD\\endinput SAME-LINE\n\\input{absent}\n")
        text, manifest, _, _ = self.prepare()
        self.assertIn("BEFORECHILDSAME-LINE AFTER", text)
        self.assertNotIn("absent", text)
        self.assertNotIn("\\endinput", text)
        self.assertEqual(manifest.active_tex_files, ["child.tex", "main.tex"])

    def test_end_document_does_not_discover_trailing_inputs(self):
        self.put("main.tex", "\\documentclass{article}\n\\begin{document}BODY\\end{document}\\input{absent}")
        text, _, _, _ = self.prepare()
        self.assertNotIn("absent", text)

    def test_scopes_and_known_reading_effects_cross_input_boundaries(self):
        self.document("{\\input{switch}\\def\\name@x{GOOD}}\\input{plain}")
        self.put("switch.tex", "\\makeatletter")
        self.put("plain.tex", "\\def\\name@x{PLAIN}")
        text, manifest, _, _ = self.prepare()
        self.assertIn("\\makeatletter ", text)
        self.assertIn("\\def\\name@x{GOOD}", text)
        self.assertIn("\\def\\name@x{PLAIN}", text)
        self.assertEqual(manifest.dependency_closure, "complete")

    def test_group_and_true_conditional_can_close_in_child(self):
        self.document("{\\iftrue A\\input{closer}B")
        self.put("closer.tex", "C\\fi}")
        text, _, _, _ = self.prepare()
        self.assertIn("AC\\fi } B", text)

    def test_import_directories_are_scoped_to_occurrences(self):
        self.document("\\import{one/}{part}\\import{two/}{part}", "\\usepackage{import}")
        self.put("one/part.tex", "ONE\\subimport{sub/}{leaf}")
        self.put("one/sub/leaf.tex", "LEAF")
        self.put("two/part.tex", "TWO")
        text, manifest, _, _ = self.prepare()
        self.assertIn("ONELEAF", text)
        self.assertIn("TWO", text)
        self.assertEqual([e["target"] for e in manifest.dependencies], ["one/part.tex", "one/sub/leaf.tex", "two/part.tex"])

    def test_local_styles_and_their_inputs_are_scanned_cached_and_retained(self):
        self.document("\\input{body}", "\\usepackage{custom}", name="src/paper.tex")
        style = "\\ProvidesPackage{custom}\n\\def\\private@name{BODY}\n\\input{settings}\n"
        self.put("src/custom.sty", style)
        self.put("src/settings.tex", "\\def\\another{VALUE}\n")
        self.put("src/body.tex", "TEXT")
        original = Path.read_bytes
        reads = Counter()
        def read(path):
            reads[path.resolve()] += 1
            return original(path)
        with patch.object(Path, "read_bytes", read):
            text, manifest, out, _ = self.prepare()
        self.assertIn("\\usepackage{src/custom}", text)
        self.assertNotIn("private@name", text)
        self.assertIn("\\input{src/settings.tex}", (out / "src/custom.sty").read_text())
        self.assertEqual((out / "src/settings.tex").read_bytes(), (self.root / "src/settings.tex").read_bytes())
        self.assertEqual(manifest.local_styles[0].declared_commands, ["private@name"])
        self.assertEqual(reads[self.root / "src/custom.sty"], 1)
        self.assertEqual(reads[self.root / "src/settings.tex"], 1)

    def test_bibliography_is_driven_by_active_commands_and_reads_once(self):
        self.document("\\input{section}")
        self.put("section.tex", "\\cite{real}\\def\\unused{\\cite{fake}}\\bibliography{refs}")
        self.put("refs.bib", "@misc{real,title={Selected}}\n@misc{fake,title={Excluded}}")
        text, manifest, out, _ = self.prepare()
        self.assertIn("Selected", text)
        self.assertNotIn("Excluded", text)
        self.assertIn("Excluded", (out / "bibliography.bib").read_text())
        self.assertEqual(manifest.source_reads.count("refs.bib"), 1)

    def test_existing_bibliography_joins_the_source_traversal(self):
        self.document("\\cite{key}\\bibliography{absent}")
        self.put("main.bbl", "\\begin{thebibliography}{1}\\input{entries}\\end{thebibliography}")
        self.put("entries.tex", "\\bibitem{key} FROM-CHILD")
        text, manifest, out, _ = self.prepare(root_tex="main.tex")
        self.assertIn("FROM-CHILD", text)
        self.assertNotIn("\\input", text)
        self.assertIn("FROM-CHILD", (out / "bibliography.bbl").read_text())
        self.assertEqual(manifest.active_tex_files, ["entries.tex", "main.tex"])

    def test_generated_bibliography_preserves_and_reports_unresolved_inputs(self):
        self.document("\\cite{key}\\bibliography{refs}")
        self.put("refs.bib", r"@misc{key,title={\input{hidden}}}")
        text, manifest, out, _ = self.prepare()
        self.assertIn(r"\input{hidden}", text)
        self.assertTrue((out / "master.tex").exists())
        self.assertEqual(manifest.preparation_status, "partial")
        self.assertEqual(manifest.unresolved[0]["reason"], "bibliography_reading")

    def test_fake_entries_in_stored_bibliography_source_do_not_satisfy_citations(self):
        self.document("\\cite{key}\\bibliography{absent}")
        self.put("main.bbl", "\\def\\unused{\\bibitem{key}FAKE}"
                 "\\begin{thebibliography}{1}\\bibitem{other}OTHER\\end{thebibliography}")
        with self.assertRaisesRegex(ValueError, "entries missing.*key"):
            self.prepare()

    def test_source_entry_point_cli_uses_the_new_traversal(self):
        import subprocess
        self.document("LEFT\\input{child}RIGHT")
        self.put("child.tex", "CHILD")
        result = subprocess.run([sys.executable, "-B", "-m", "src.prepare.pipeline", str(self.root)],
                                cwd=PROJECT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LEFTCHILD RIGHT", (self.root / "extracted/master.tex").read_text())

    def test_unresolved_child_preserves_input_and_publishes_without_guessing_dormancy(self):
        self.document("\\input{part}")
        self.put("part.tex", "\\input{\\computed}\n")
        self.put("maybe.tex", "POSSIBLE")
        text, _, _, _ = self.prepare(root_tex="main.tex")
        out = self.root / "extracted"
        self.assertTrue((out / "master.tex").exists())
        self.assertIn("\\input{\\computed}", text)
        self.assertNotIn("\\input{part}", text)
        self.assertIn("\\end{document}", text)
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual(manifest["dependency_closure"], "unresolved")
        self.assertEqual(manifest["dormant_tex_files"], [])
        self.assertIn("maybe.tex", manifest["unclassified_files"])
        self.assertEqual(manifest["preparation_status"], "partial")
        self.assertEqual(manifest["entrypoint"], "master.tex")
        self.assertEqual(manifest["unresolved"][0]["source"], "part.tex")

    def test_output_inputs_and_inputs_outside_project_fail(self):
        cases = ["\\input{extracted/old}", "\\input{../outside}"]
        for body in cases:
            with self.subTest(body=body):
                self.document(body)
                self.put("extracted/old.tex", "GENERATED")
                with self.assertRaises(PreparationUnresolved):
                    self.prepare(root_tex="main.tex")

    def test_uninterpreted_expressions_preserve_spans_and_continue_assembly(self):
        for pending in (r"\unknown{ARG}", "$x+y$", r"\later{ARG}",
                        r"\title{\input{hidden}}", r"\begin{unknown}BODY\end{unknown}"):
            with self.subTest(pending=pending):
                suffix = pending + "% keep exactly\r\n  TAIL\n\\input{later-file}\n\\end{document}"
                source = "\\documentclass{article}\n\\begin{document}\\def\\later#1{#1}\\input{done}" + suffix
                path = self.put("main.tex", source)
                self.put("done.tex", "FINISHED")
                self.put("later-file.tex", "UNVISITED")
                before = path.read_bytes()
                text, manifest, out, ledger = self.prepare(root_tex="main.tex")
                self.assertIn("FINISHED", text)
                self.assertNotIn("\\input{done}", text)
                self.assertIn(pending, text)
                self.assertIn("UNVISITED", text)
                self.assertNotIn("\\input{later-file}", text)
                self.assertEqual(path.read_bytes(), before)
                self.assertTrue(manifest.requirements)
                self.assertIn("later-file.tex", manifest.active_tex_files)
                self.assertEqual(manifest.dormant_tex_files, [])
                self.assertIn("requirement.deferred", (out / "preparation.jsonl").read_text())
                for segment in ledger.segments:
                    if segment["operation"] == "DEFER_INTERPRETATION":
                        a, b = segment["generated"]
                        c, d = segment["source"]
                        self.assertEqual(text[a:b], source[c:d])

    def test_missing_class_and_package_bindings_allow_iteration(self):
        for declaration, reason in ((r"\documentclass{notyetbound}", "class_binding"),
                                    (r"\usepackage{notyetbound}", "package_binding")):
            with self.subTest(reason=reason):
                suffix = declaration + "\n% keep\n\\begin{document}FULL BODY\\end{document}"
                self.put("main.tex", suffix if reason == "class_binding" else "\\documentclass{article}\n" + suffix)
                text, manifest, out, _ = self.prepare(root_tex="main.tex")
                self.assertIn("FULL BODY", text)
                self.assertEqual(text.count(declaration), 1)
                self.assertEqual(manifest.requirements[0]["reason"], reason)
                self.assertEqual(manifest.entrypoint, "master.tex")
                self.assertIn(reason, (out / "preparation.jsonl").read_text())

    def test_unexpanded_nested_expression_does_not_undo_splices(self):
        self.document("\\input{done}\\input{outer}% retain\nTAIL")
        self.put("done.tex", "COMPLETED")
        self.put("outer.tex", "OUTER\\input{inner}AFTER-INNER")
        self.put("inner.tex", "PREFIX\\unknown% no physical newline")
        text, manifest, _, _ = self.prepare(root_tex="main.tex")
        self.assertIn("COMPLETED", text)
        self.assertIn("OUTERPREFIX\\unknown AFTER-INNER", text)
        self.assertIn("TAIL", text)
        self.assertNotIn("\\input{outer}", text)
        self.assertEqual(manifest.requirements[0]["source"], "inner.tex")
        self.assertEqual(manifest.preserved_source_spans, [])

    def test_local_package_gap_preserves_declaration_and_remaining_manuscript(self):
        self.document("BODY\\input{later}", "\\usepackage{custom}")
        style = "\\ProvidesPackage{custom}\n\\unknown{KEEP}\n"
        self.put("custom.sty", style)
        self.put("later.tex", "UNVISITED")
        text, manifest, out, _ = self.prepare(root_tex="main.tex")
        self.assertIn("\\usepackage{custom}", text)
        self.assertIn("BODYUNVISITED", text)
        self.assertEqual((out / "custom.sty").read_text(), style)
        self.assertEqual(manifest.requirements[0]["source"], "custom.sty")
        self.assertEqual(manifest.source_reads.count("custom.sty"), 1)

    def test_bibliography_fields_do_not_require_expansion_bindings(self):
        self.document("\\cite{key}\\bibliography{refs}")
        self.put("refs.bib", r"@misc{key,title={A $x$ and \unknown{Y}},url={https://example.org/a_b}}")
        text, manifest, out, _ = self.prepare()
        self.assertIn(r"A $x$ and \unknown{Y}", text)
        self.assertIn(r"\url{https://example.org/a_b}", text)
        self.assertIn(r"\bibitem{key}", text)
        self.assertEqual(manifest.bibliography.preparation_backend, "native-bibtex")
        self.assertEqual(manifest.bibliography.citations_count, 1)
        self.assertTrue((out / "bibliography.bbl").exists())
        self.assertTrue((out / "bibliography.bib").exists())

    def test_partial_citation_discovery_keeps_all_available_entries(self):
        self.document("\\cite{first}\\bibliography{refs}\\unknown\\cite{second}")
        self.put("refs.bib", "@misc{first,title={FIRST}}\n@misc{second,title={SECOND}}")
        text, manifest, _, _ = self.prepare()
        self.assertIn("\\bibitem{first}", text)
        self.assertIn("\\bibitem{second}", text)
        self.assertIn("\\unknown \\cite{second}", text)
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertEqual(manifest.source_dependency_closure, "complete")
        self.assertEqual(manifest.dependency_closure, "unresolved")

    def test_generated_bibliography_expression_keeps_later_edits_and_assets(self):
        suffix = "  % KEEP COMMENT\n\\includegraphics{plot.svg}\\input{tail}\\end{document}"
        self.put("main.tex", "\\documentclass{article}\\usepackage{graphicx}"
                 "\\begin{document}\\cite{key}\\bibliography{refs}" + suffix)
        self.put("refs.bib", r"@misc{key,title={\unknown{Title}}}")
        self.put("tail.tex", "TAIL")
        self.put("plot.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>')
        text, manifest, out, _ = self.prepare()
        self.assertIn("\\bibitem{key}", text)
        self.assertIn("TAIL", text)
        self.assertNotIn("\\input{tail}", text)
        self.assertEqual([i.rel_path for i in manifest.active_images], ["plot.svg"])
        self.assertTrue((out / "plot.svg").exists())

    def test_generated_bibliography_in_child_stays_embedded_with_unexpanded_fields(self):
        self.document("\\cite{key}\\input{part}TAIL")
        self.put("part.tex", "PREFIX\\bibliography{refs}CHILD-TAIL")
        self.put("refs.bib", r"@misc{key,title={\unknown{Title}}}")
        text, manifest, out, _ = self.prepare()
        self.assertNotIn("\\input{part}", text)
        self.assertIn("PREFIX", text)
        self.assertIn("CHILD-TAIL", text)
        self.assertIn("\\bibitem", text)
        self.assertIn("\\bibitem{key}", (out / "bibliography.bbl").read_text())
        self.assertEqual(manifest.requirements[0]["source"], "bibliography.bbl")

    def test_partial_discovery_does_not_hide_a_known_missing_bibliography_entry(self):
        self.document("\\cite{missing}\\bibliography{refs}\\unknown")
        self.put("refs.bib", "@misc{other,title={OTHER}}")
        with self.assertRaisesRegex(ValueError, "missing"):
            self.prepare()

    def test_multiple_bibliography_sites_preserve_later_site_without_duplicate_bbl(self):
        self.document("\\cite{key}\\bibliography{refs}BETWEEN\\bibliography{refs}AFTER")
        self.put("main.bbl", r"\begin{thebibliography}{1}\bibitem{key}CONTENT\end{thebibliography}")
        text, manifest, _, _ = self.prepare()
        self.assertEqual(text.count("\\bibitem{key}"), 1)
        self.assertIn("BETWEEN\\bibliography{refs}AFTER", text)
        self.assertEqual(manifest.unresolved[0]["reason"], "bibliography_sites")

    def test_no_observed_citations_keeps_available_entries_in_canonical_resource(self):
        self.document("\\bibliography{refs}")
        self.put("refs.bib", "@misc{key,title={CONTENT}}")
        text, manifest, out, _ = self.prepare()
        self.assertNotIn("\\bibliography{refs}", text)
        self.assertNotIn("\\bibitem{key}", text)
        self.assertIn("CONTENT", (out / "bibliography.bib").read_text())
        self.assertEqual(manifest.bibliography.preparation_backend, "native-bibtex")

    def test_partial_rerun_can_become_complete_without_stale_diagnostics(self):
        self.document(r"\input{\unknown}")
        _, manifest, out, _ = self.prepare()
        self.assertEqual(manifest.preparation_status, "partial")
        self.document("BODY")
        text, manifest, _, _ = self.prepare()
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertEqual(manifest.unresolved, [])
        self.assertEqual(manifest.preserved_source_spans, [])
        self.assertNotIn("\\unknown", text)
        log = (out / "preparation.jsonl").read_text()
        self.assertEqual(sum(e["code"] == "attempt.started" for e in read_events(out / "preparation.jsonl")), 2)
        self.assertIn('"preparation_status":"partial"', log)
        self.assertEqual(list(read_events(out / "preparation.jsonl"))[-1]["data"]["preparation_status"], "complete")

    def test_cache_remembers_strict_decode_failure(self):
        path = self.put("bad.tex", "")
        path.write_bytes(b"\xff")
        store = SourceStore(self.root)
        original = Path.read_bytes
        reads = Counter()
        def read(path):
            reads[path] += 1
            return original(path)
        with patch.object(Path, "read_bytes", read):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "byte 0"):
                    store.document(path)
        self.assertEqual(reads[path], 1)

    def test_graphics_are_resolved_in_scope_and_rewritten_by_argument_span(self):
        self.document("\\graphicspath{{one/}}\\includegraphics{plot.svg}"
                      "{\\graphicspath{{two/}}\\includegraphics{plot.svg}}"
                      "\\includegraphics{plot.svg}\\verb|\\includegraphics{plot.svg}|",
                      "\\usepackage{graphicx}")
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
        self.put("one/plot.svg", svg)
        self.put("two/plot.svg", svg)
        text, manifest, out, _ = self.prepare()
        self.assertEqual(text.count("\\includegraphics{one/plot.svg}"), 2)
        self.assertIn("\\includegraphics{two/plot.svg}", text)
        self.assertIn("\\verb|\\includegraphics{plot.svg}|", text)
        self.assertEqual([i.rel_path for i in manifest.active_images], ["one/plot.svg", "two/plot.svg"])
        self.assertTrue((out / "one/plot.svg").exists())

    def test_ambiguous_extension_and_ambiguous_roots_are_explicit(self):
        self.document("\\includegraphics{plot}", "\\usepackage{graphicx}")
        self.put("plot.png", "PNG")
        self.put("plot.pdf", "PDF")
        with self.assertRaisesRegex(PreparationUnresolved, "ambiguous_dependency"):
            self.prepare()
        self.document("OTHER", name="other.tex")
        with self.assertRaisesRegex(ValueError, "Root selection is unresolved"):
            self.prepare()

    def test_nonfirst_pdf_page_is_not_silently_converted_as_page_one(self):
        self.document("\\includegraphics[page=2]{plot.pdf}", "\\usepackage{graphicx}")
        self.put("plot.pdf", "PDF")
        with self.assertRaisesRegex(RuntimeError, "Failed to convert PDF"):
            self.prepare()

    def test_explicit_assets_with_same_stem_have_distinct_derivatives(self):
        from PIL import Image
        self.document("\\includegraphics{plot.svg}\\includegraphics{plot.png}", "\\usepackage{graphicx}")
        self.put("plot.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>')
        Image.new("RGB", (1, 1), "red").save(self.root / "plot.png")
        text, _, out, _ = self.prepare()
        self.assertIn("\\includegraphics{plot.svg.svg}", text)
        self.assertIn("\\includegraphics{plot.png.svg}", text)
        self.assertNotEqual((out / "plot.svg.svg").read_bytes(), (out / "plot.png.svg").read_bytes())

    def test_failed_rerun_preserves_prior_master_and_appends_log(self):
        self.document("OK")
        _, _, out, _ = self.prepare()
        self.document("\\input{missing}")
        with self.assertRaises(PreparationUnresolved):
            self.prepare()
        self.assertIn("OK", (out / "master.tex").read_text())
        log = (out / "preparation.jsonl").read_text()
        self.assertIn("attempt.published", log)
        self.assertIn("attempt.failed", log)
        self.assertEqual(sum(e["code"] == "attempt.started" for e in read_events(out / "preparation.jsonl")), 2)

    def test_includeonly_and_include_page_boundaries(self):
        self.document("A\\include{one}B\\include{two}C", "\\includeonly{one}")
        self.put("one.tex", "ONE")
        self.put("two.tex", "TWO")
        text, manifest, _, _ = self.prepare()
        self.assertIn("ONE", text)
        self.assertNotIn("TWO", text)
        self.assertEqual(text.count("\\clearpage"), 3)
        self.assertEqual(manifest.dormant_tex_files, ["two.tex"])

    def test_crlf_literal_and_definition_provenance_uses_unchanged_buffers(self):
        definition = "\\def\\foo{A% comment\r\n  B}"
        literal = "\\begin{verbatim}\r\n\\input{missing}\r\n\\end{verbatim}"
        source = "\\documentclass{article}\r\n\\begin{document}\r\n" + definition + literal + "\\end{document}"
        path = self.put("main.tex", source)
        before = path.read_bytes()
        text, _, _, ledger = self.prepare()
        self.assertEqual(path.read_bytes(), before)
        self.assertIn(definition, text)
        self.assertIn(literal, text)
        for s in ledger.segments:
            if s['operation'] == 'IDENTITY':
                a, b = s['generated']
                c, d = s['source']
                self.assertEqual(text[a:b], source[c:d])

    def test_package_activation_happens_at_the_declaration(self):
        self.document("\\includegraphics{plot.svg}\\usepackage{graphicx}")
        self.put("plot.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
        text, manifest, _, _ = self.prepare()
        self.assertIn("\\includegraphics{plot.svg}\\usepackage{graphicx}", text)
        self.assertEqual(manifest.requirements[0]["reason"], "package_not_loaded")
        self.assertEqual(manifest.active_images, [])

    def test_skipping_does_not_dispatch_literal_commands(self):
        self.document("\\iffalse \\verb|\\fi|\\input{live}")
        self.put("live.tex", "LIVE")
        text, manifest, _, _ = self.prepare()
        self.assertIn("LIVE", text)
        self.assertEqual(manifest.active_tex_files, ["live.tex", "main.tex"])

    def test_comment_spacing_and_input_joins_preserve_paragraphs(self):
        self.document("foo% comment\nbar foo % comment\nbar\n\n\\input{part}\nTAIL")
        self.put("part.tex", "CHILD\n")
        text, _, _, _ = self.prepare()
        self.assertIn("foobar foo bar", text)
        self.assertIn("\\par CHILD", text)
        self.assertIn("CHILD  TAIL", text)
        self.assertEqual(text.count("\\par"), 2)  # empty preamble line plus explicit body paragraph


if __name__ == "__main__":
    unittest.main()
