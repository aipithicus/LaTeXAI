"""Unresolved execution must not hide independently preparable later source."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from reader_support import reload_catalog
from src.bindings.resolver import BindingResolver
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import (ConditionalRegion, DeferredRegion, ReadingBoundary,
                                   SourceCommand, UncertainMeaning)
from src.reading.coverage import ReadingCoverage
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader


class ConditionalCaptureTests(unittest.TestCase):
    def scan(self, source, *, preparation=True, catalog=None, packages=()):
        resolver = BindingResolver(catalog)
        for name in packages:
            resolver.load_package(name)
        self.context = resolver.new_context()
        self.reader = TexReader(source, catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        items = list(StructuralDispatcher(self.reader, self.context, resolver,
                    source_commands=True, preparation=preparation))
        return items

    def test_unknown_predicate_preserves_both_branches_and_resumes(self):
        body = "\\if0\\blind{A % keep\n}\\else{B}\\fi"
        items = self.scan(body + r"\input{tail}")
        region = next(i for i in items if isinstance(i, ConditionalRegion))
        self.assertEqual(self.reader.text[region.span.start:region.span.end], body)
        self.assertTrue(any(isinstance(i, SourceCommand) and i.value("target") == "tail" for i in items))
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))
        self.assertTrue(ReadingCoverage(self.reader.basis, items).unknown.covers(region.span))

    def test_strict_reader_still_requires_predicate_evaluation(self):
        items = self.scan(r"\if0\blind A\fi\input{tail}", preparation=False)
        self.assertEqual(items[-1].reason, "unsupported_conditional")

    def test_nested_conditions_are_retained_not_selected(self):
        items = self.scan(r"\if0\blind\iftrue A\else B\fi\else C\fi\input{tail}")
        self.assertEqual(sum(isinstance(i, ConditionalRegion) for i in items), 1)
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))

    def test_two_operand_header_can_itself_name_a_conditional(self):
        items = self.scan(r"\ifx\fi\else A\fi\input{tail}")
        region = next(i for i in items if isinstance(i, ConditionalRegion))
        self.assertEqual(len(region.markers), 1)
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))

    def test_one_operand_header_can_itself_name_a_conditional(self):
        items = self.scan(r"\ifdefined\fi A\else B\fi\input{tail}")
        region = next(i for i in items if isinstance(i, ConditionalRegion))
        self.assertEqual(len(region.markers), 2)
        self.assertTrue(any(isinstance(i, SourceCommand) and i.value("target") == "tail" for i in items))
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))

    def test_engine_tests_nest_only_once_iftex_is_loaded(self):
        body = r"\ifPDFTeX\usepackage{inputenc}\else\ifXeTeX X\fi\usepackage{fontspec}\fi"
        self.assertTrue(any(isinstance(i, ReadingBoundary) for i in self.scan(body + r"\input{tail}")))
        items = self.scan(body + r"\input{tail}", packages=("iftex",))
        region = next(i for i in items if isinstance(i, ConditionalRegion))
        self.assertEqual(self.reader.text[region.span.start:region.span.end], body)
        self.assertTrue(any(isinstance(i, SourceCommand) and i.value("target") == "tail" for i in items))
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))

    def test_skipped_and_active_readings_must_agree(self):
        for body in (r"\verb|\fi|", r"\def\x{\fi}", r"\unknown{\fi}",
                     r"$\fi$", r"\ifx\fi\x A\fi"):
            with self.subTest(body=body):
                items = self.scan(r"\if0\blind " + body + r"\fi\input{tail}")
                self.assertIsInstance(items[-1], ReadingBoundary)
                self.assertEqual(items[-1].reason, "conditional_reading")
                self.assertFalse(any(isinstance(i, SourceCommand) for i in items))

    def test_comments_do_not_create_conditional_markers(self):
        items = self.scan("\\if0\\blind A% \\else \\fi\r\nB\\fi\\input{tail}")
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))

    def test_scope_crossing_and_unclosed_conditionals_remain_explicit(self):
        for source, reason in ((r"\if0\blind{A\else B}\fi", "conditional_scope"),
                               (r"\if0\blind A", "unclosed_conditional"),
                               (r"\if0\blind A\else B\else C\fi", "conditional_structure")):
            with self.subTest(source=source):
                self.assertEqual(self.scan(source)[-1].reason, reason)

    def test_direct_reading_effect_is_not_guessed(self):
        items = self.scan(r"\if0\blind\catcode`\%=12 A\fi\input{tail}")
        self.assertIsInstance(items[-1], ReadingBoundary)
        self.assertEqual(self.context.catcodes["%"], 14)

    def test_uncertain_boolean_retains_branches_and_setters_do_not_execute(self):
        items = self.scan(r"\newif\ifflag\unknown\ifflag\flagtrue A\else B\fi\input{tail}")
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))
        self.assertFalse(self.context.lookup_meaning("ifflag").truth)
        self.assertIsNotNone(self.context.lookup_meaning("ifflag").uncertain)

    def test_unexecuted_definitions_do_not_install_and_old_meanings_do_not_win(self):
        items = self.scan(r"\def\x{OLD}\if0\blind\def\x{NEW}\fi\input{tail}")
        self.assertIsInstance(self.context.lookup_meaning("x"), UncertainMeaning)
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))
        self.assertEqual(self.scan(r"\def\x{OLD}\if0\blind\def\x{NEW}\fi\x")[-1].reason, "uncertain_meaning")

    def test_yaml_selects_capture_recipe_without_command_name_switches(self):
        catalog = deepcopy(BindingCatalog())
        rules = catalog.engine_bindings["core_latex"]["reading"]["conditionals"]
        rule = next(r for r in rules if r["name"] == r"\ifx")
        rule["name"] = r"\compare"
        items = self.scan(r"\compare\a\b A\fi\input{tail}", catalog=reload_catalog(self, catalog))
        self.assertTrue(any(isinstance(i, ConditionalRegion) for i in items))

    def test_unsupported_operand_grammar_is_explicit(self):
        self.assertEqual(self.scan(r"\ifnum\x=1 A\fi")[-1].reason, "conditional_header")

    def test_overloaded_metadata_signature_is_preserved_without_guessing(self):
        source = r"\if0\blind{\author[1]{Author\thanks{Grant}}}\fi\input{tail}"
        items = self.scan(source)
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))
        region = next(i for i in items if isinstance(i, ConditionalRegion))
        self.assertIn(r"\author[1]", source[region.span.start:region.span.end])
        self.assertFalse(any(o.command is not None and o.command.name == r"\author" for o in region.observations))


class ConditionalPreparationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def prepare(self):
        text, manifest, output, ledger = preprocess_paper(str(self.root), root_tex="main.tex")
        saved = json.loads((output / "master.provenance.json").read_text())
        self.assertTrue(all(not c["unaccounted"] for c in saved["source_coverage"]), saved["source_coverage"])
        for row in (*manifest.requirements, *manifest.candidate_dependencies):
            self.assertNotEqual(row["location_status"], "pending")
            for loc in row["locations"]:
                self.assertTrue(0 <= loc["start"] <= loc["end"] <= len(text))
        return text, manifest, output, ledger

    def test_later_inputs_bibliography_and_assets_are_prepared(self):
        region = r"\if0\blind{\title{A}}\else{\title{B}}\fi"
        original = (r"\documentclass{article}\usepackage{unknown,graphicx}" + region +
                    r"\input{tail}\includegraphics{figure.png}\bibliography{refs}")
        main = self.put("main.tex", original)
        self.put("tail.tex", "TAIL")
        self.put("main.bbl", r"\begin{thebibliography}{1}\bibitem{k}REFERENCE\end{thebibliography}")
        Image.new("RGB", (2, 2), "red").save(self.root / "figure.png")
        text, manifest, output, _ = self.prepare()
        self.assertIn(region + " TAIL", text)
        self.assertIn("REFERENCE", text)
        self.assertIn("figure.svg", text)
        self.assertTrue((output / "bibliography.bbl").is_file())
        self.assertTrue((output / "figure.svg").is_file())
        self.assertFalse(manifest.unresolved)
        self.assertFalse(manifest.preserved_source_spans)
        self.assertEqual(main.read_text(), original)

    def test_branch_inputs_recursive_and_repeated_are_candidates_with_cached_reads(self):
        self.put("main.tex", r"\if0\blind\input{child}\else\input{child}\fi\input{tail}")
        self.put("child.tex", r"CHILD\input{leaf}")
        self.put("leaf.tex", "LEAF% final comment")
        self.put("tail.tex", "TAIL")
        reads = Counter()
        original = Path.read_bytes
        def read(path):
            reads[path.resolve()] += 1
            return original(path)
        with patch.object(Path, "read_bytes", read):
            text, manifest, _, ledger = self.prepare()
        self.assertEqual(text.count("LEAF%\n"), 2)
        self.assertNotIn('final comment', text)
        self.assertIn(r"\fi TAIL", text)
        self.assertNotIn(r"\input", text)
        self.assertEqual(manifest.candidate_tex_files, ["child.tex", "leaf.tex"])
        self.assertEqual([d["target"] for d in manifest.dependencies], ["tail.tex"])
        self.assertEqual(len(manifest.candidate_dependencies), 4)
        self.assertTrue(all(d["status"] == "prepared" for d in manifest.candidate_dependencies))
        self.assertEqual(len({o["id"] for o in manifest.input_occurrences}), 6)
        self.assertTrue(all(reads[self.root / name] == 1 for name in manifest.source_reads))
        self.assertEqual(ledger.master_length, len(text))

    def test_missing_computed_or_unsafe_branch_input_does_not_hide_tail(self):
        self.put("main.tex", r"\if0\blind\input{missing}\input{\name}\input{bad}\fi\input{tail}")
        self.put("bad.tex", r"\verb|\fi|")
        self.put("tail.tex", "TAIL")
        text, manifest, _, _ = self.prepare()
        self.assertIn(r"\input{missing}", text)
        self.assertIn(r"\input{\name}", text)
        self.assertIn(r"\input{bad}", text)
        self.assertIn(r"\fi TAIL", text)
        self.assertEqual({d["reason"] for d in manifest.candidate_dependencies},
                         {"missing_dependency", "computed_argument", "conditional_input"})

    def test_input_cycle_is_local_and_later_source_remains_preparable(self):
        self.put("main.tex", r"\if0\blind\input{child}\fi\input{tail}")
        self.put("child.tex", r"CHILD\input{child}")
        self.put("tail.tex", "TAIL")
        text, manifest, _, _ = self.prepare()
        self.assertIn(r"CHILD\input{child}", text)
        self.assertIn("TAIL", text)
        self.assertTrue(any(r["reason"] == "input_cycle" for r in manifest.requirements))

    def test_branch_assets_are_observations_not_active_images(self):
        self.put("main.tex", r"\usepackage{graphicx}\if0\blind\includegraphics{a.png}\else\includegraphics{b.png}\fi\input{tail}")
        self.put("tail.tex", "TAIL")
        for name in ("a.png", "b.png"):
            Image.new("RGB", (2, 2), "red").save(self.root / name)
        text, manifest, output, _ = self.prepare()
        self.assertIn("a.svg", text)
        self.assertIn("b.svg", text)
        self.assertEqual(manifest.active_images, [])
        self.assertEqual(len(manifest.candidate_images), 2)
        self.assertEqual({d["status"] for d in manifest.candidate_dependencies}, {"prepared"})

    def test_opaque_and_literal_hidden_inputs_are_not_promoted(self):
        region = r"\if0\blind\unknown{\input{hidden}}\verb|\input{fake}|\fi"
        self.put("main.tex", region + r"\input{tail}")
        self.put("tail.tex", "TAIL")
        text, manifest, _, _ = self.prepare()
        self.assertIn(region, text)
        self.assertEqual(manifest.candidate_dependencies, [])
        self.assertTrue(any(r["reason"] == "deferred_dependency" for r in manifest.requirements))

    def test_ambiguous_structure_preserves_suffix_instead_of_guessing(self):
        source = r"\if0\blind\verb|\fi|\fi\input{tail}"
        self.put("main.tex", source)
        self.put("tail.tex", "TAIL")
        text, manifest, _, _ = self.prepare()
        self.assertEqual(text, source)
        self.assertEqual(manifest.unresolved[0]["reason"], "conditional_reading")
        self.assertEqual(manifest.dependencies, [])

    def test_bibliography_inside_unbound_wrapper_is_inlined_and_enriched(self):
        self.put("main.tex", r"\if0\blind A\else B\fi\begin{unboundspacing}"
                 r"\bibliographystyle{plain}\bibliography{refs}\end{unboundspacing}\input{tail}")
        bbl = r"\begin{thebibliography}{1}\bibitem{k}REFERENCE\end{thebibliography}"
        self.put("main.bbl", bbl)
        self.put("refs.bib", "@misc{k,title={Enrichment}}")
        self.put("tail.tex", "TAIL")
        text, manifest, output, _ = self.prepare()
        self.assertIn(r"\begin{unboundspacing}" + bbl + r"\end{unboundspacing}", text)
        self.assertNotIn(r"\bibliography{", text)
        self.assertNotIn(r"\bibliographystyle", text)
        self.assertEqual(manifest.bibliography.citations_count, 1)
        self.assertIn("Enrichment", (output / "bibliography.bib").read_text())
        self.assertEqual((output / "bibliography.bbl").read_text(), bbl)
        self.assertIn("TAIL", text)
        site = next(d for d in manifest.candidate_dependencies if d["kind"] == "formatted_bibliography")
        self.assertEqual("".join(text[l["start"]:l["end"]] for l in site["locations"]), bbl)

    def test_unresolved_bibliography_candidate_does_not_abort_tail(self):
        self.put("main.tex", r"\begin{unbound}\bibliography{refs}\end{unbound}\input{tail}")
        self.put("main.bbl", r"\catcode`\%=\computed")
        self.put("tail.tex", "TAIL")
        text, manifest, _, _ = self.prepare()
        self.assertIn(r"\bibliography{refs}", text)
        self.assertIn("TAIL", text)
        self.assertTrue(any(r["reason"] == "bibliography_reading" for r in manifest.requirements))

    def test_conditional_native_bibliography_retains_branch_and_canonical_resource(self):
        self.put("main.tex", r"\cite{k}\if0\blind\bibliography{refs}\fi\input{tail}")
        self.put("refs.bib", "@misc{k,title={Native reference}}")
        self.put("tail.tex", "TAIL")
        text, manifest, output, _ = self.prepare()
        self.assertIn(r"\if0\blind\begin{thebibliography}", text)
        self.assertIn("Native reference", text)
        self.assertIn(r"\fi TAIL", text)
        self.assertTrue((output / "bibliography.bib").is_file())

    def test_explicit_input_extension_is_not_searched_with_another_suffix(self):
        self.put("main.tex", r"\if0\blind\input{child.tex}\fi")
        self.put("child.tex", "RIGHT")
        self.put("child.tex.tex", "WRONG")
        text, manifest, _, _ = self.prepare()
        self.assertIn("RIGHT", text)
        self.assertNotIn("WRONG", text)
        self.assertEqual(manifest.candidate_dependencies[0]["status"], "prepared")

    def test_local_style_input_is_not_flattened(self):
        self.put("main.tex", r"\if0\blind\input{local.sty}\fi\input{tail}")
        self.put("local.sty", "LOCAL STYLE")
        self.put("tail.tex", "TAIL")
        text, manifest, _, _ = self.prepare()
        self.assertIn(r"\input{local.sty}", text)
        self.assertNotIn("LOCAL STYLE", text)
        self.assertIn("TAIL", text)
        self.assertEqual(manifest.candidate_dependencies[0]["reason"], "retained_code_input")

    def test_input_after_unexecuted_search_change_is_not_prepared_with_stale_paths(self):
        self.put("main.tex", r"\usepackage{graphicx}\if0\blind\graphicspath{{figures/}}\input{child}\fi\input{tail}")
        self.put("child.tex", r"\includegraphics{same.png}")
        self.put("tail.tex", "TAIL")
        text, manifest, _, _ = self.prepare()
        self.assertIn(r"\input{child}", text)
        self.assertIn("TAIL", text)
        self.assertEqual(manifest.candidate_dependencies[0]["reason"], "input_search_context")

    def test_unsafe_native_bibliography_keeps_canonical_enrichment_and_tail(self):
        self.put("main.tex", r"\cite{k}\if0\blind\bibliography{refs}\fi\input{tail}")
        self.put("refs.bib", r"@misc{k,title={\verb|\fi|}}")
        self.put("tail.tex", "TAIL")
        text, manifest, output, _ = self.prepare()
        self.assertIn(r"\bibliography{bibliography}", text)
        self.assertIn("TAIL", text)
        self.assertEqual(manifest.bibliography.preparation_backend, "deferred-reading")
        self.assertIn(r"\verb|\fi|", (output / "bibliography.bib").read_text())


if __name__ == "__main__":
    unittest.main()
