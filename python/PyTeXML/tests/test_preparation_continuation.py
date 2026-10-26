"""Preparation breadth must not depend on complete interpretation bindings."""
from collections import Counter
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper
from src.bindings.resolver import BindingResolver
from src.reading.dispatcher import StructuralDispatcher
from src.reading.contracts import DeferredRegion, ReadingBoundary, LiteralRegion, SourceCommand
from src.reading.coverage import ReadingCoverage
from src.reading.tex_reader import TexReader


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def prepare(self):
        return preprocess_paper(str(self.root), root_tex="main.tex")

    def test_unknown_package_and_expressions_do_not_hide_inputs_or_existing_bbl(self):
        source = (r"\documentclass{article}\usepackage{notyetbound}\begin{document}"
                  r"$x+y$ \ordinary{Text}\input{one}\input{two}\bibliography{refs}\end{document}")
        self.put("main.tex", source)
        self.put("one.tex", "FIRST CHILD")
        self.put("two.tex", "SECOND CHILD")
        self.put("main.bbl", r"\begin{thebibliography}{1}\bibitem{key}BIBLIOGRAPHY BODY\end{thebibliography}")
        reads = Counter()
        original = Path.read_bytes
        def read(path):
            reads[path.resolve()] += 1
            return original(path)
        with patch.object(Path, "read_bytes", read):
            text, manifest, output, ledger = self.prepare()
        for expected in ("FIRST CHILD", "SECOND CHILD", "BIBLIOGRAPHY BODY", "$x+y$", r"\ordinary{Text}"):
            self.assertIn(expected, text)
        self.assertNotIn(r"\input", text)
        self.assertNotIn(r"\bibliography{", text)
        self.assertEqual({r["reason"] for r in manifest.requirements},
                         {"package_binding", "math_interpretation", "unknown_construct"})
        self.assertEqual(manifest.source_dependency_closure, "complete")
        self.assertEqual(manifest.dependency_closure, "unresolved")
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertEqual(manifest.preserved_source_spans, [])
        self.assertTrue(all(reads[self.root / p] == 1 for p in manifest.source_reads))
        self.assertEqual((self.root / "main.tex").read_text(), source)
        self.assertEqual(ledger.master_length, len(text))
        self.assertIn("BIBLIOGRAPHY BODY", (output / "bibliography.bbl").read_text())

    def test_computed_reference_defers_only_that_command(self):
        self.put("main.tex", r"\documentclass{article}\input{\computed}\input{real}")
        self.put("real.tex", "REAL")
        text, manifest, _, _ = self.prepare()
        self.assertIn(r"\input{\computed}", text)
        self.assertIn("REAL", text)
        self.assertEqual(manifest.preparation_status, "partial")
        self.assertEqual(manifest.unresolved[0]["reason"], "computed_argument")

    def test_unclassified_literal_options_do_not_roll_back_nested_inputs(self):
        source = (r'\documentclass{article}\usepackage{listings}\begin{document}'
                  r'\input{section}\input{after}\end{document}')
        block = ('\\begin{lstlisting}[style=future]\n'
                 '\\input{never}\n% literal comment\n\\end{lstlisting}\n')
        self.put('main.tex', source)
        self.put('section.tex', r'\input{before}\lstdefinestyle{future}{unknown=x}' + block + 'SECTION END')
        self.put('before.tex', 'BEFORE')
        self.put('after.tex', 'AFTER')
        text, manifest, _, ledger = self.prepare()
        for content in ('BEFORE', block.rstrip(), 'SECTION END', 'AFTER'):
            self.assertIn(content, text)
        self.assertNotIn(r'\input{section}', text)
        self.assertFalse(manifest.preserved_source_spans)
        self.assertEqual([r['reason'] for r in manifest.requirements if r['reason'] == 'literal_configuration'],
                         ['literal_configuration'])
        self.assertFalse([d for d in manifest.dependencies if d['target'] == 'never.tex'])
        self.assertFalse([u for u in manifest.units if u['location_status'] == 'unmapped'])
        self.assertEqual((self.root / 'main.tex').read_text(), source)
        self.assertEqual(ledger.master_length, len(text))

    def test_unframeable_child_is_retained_and_caller_continues(self):
        source = r'\documentclass{article}\input{section}\input{after}'
        child = r'BEFORE \input{grand}\catcode`\%=\computed \input{tail}'
        self.put('main.tex', source)
        self.put('section.tex', child)
        self.put('grand.tex', 'GRAND')
        self.put('tail.tex', 'TAIL')
        self.put('after.tex', 'AFTER')
        text, manifest, output, ledger = self.prepare()
        self.assertIn(r'\input{section.tex}', text)
        self.assertIn('AFTER', text)
        self.assertEqual((output / 'section.tex').read_text(), child)
        self.assertEqual((output / 'grand.tex').read_text(), 'GRAND')
        self.assertEqual((output / 'tail.tex').read_text(), 'TAIL')
        self.assertTrue(any(r['reason'] == 'retained_code_reading' for r in manifest.requirements))
        self.assertFalse([u for u in manifest.units if u['location_status'] == 'unmapped'])
        self.assertFalse([s for s in ledger.source_coverage if s['unaccounted']])
        self.assertEqual((self.root / 'main.tex').read_text(), source)

    def test_literal_candidate_input_is_packaged_without_executing_its_owner(self):
        child = r'\input{nested} ABSTRACT'
        self.put('main.tex', r'\documentclass{article}\unknown{\input{abstract}}\input{after}')
        self.put('abstract.tex', child)
        self.put('nested.tex', 'NESTED')
        self.put('after.tex', 'AFTER')
        text, manifest, output, _ = self.prepare()
        self.assertIn(r'\unknown{\input{abstract}}', text)
        self.assertIn('AFTER', text)
        self.assertNotIn('ABSTRACT', text)
        self.assertEqual((output / 'abstract.tex').read_text(), child)
        self.assertEqual((output / 'nested.tex').read_text(), 'NESTED')
        self.assertEqual([d['target'] for d in manifest.dependencies], ['after.tex'])
        requirement, = [r for r in manifest.requirements if r['reason'] == 'deferred_dependency']
        self.assertEqual(requirement['activity'], 'unresolved')
        self.assertEqual(requirement['materialization'], 'prepared')

    def test_root_residue_retains_literal_input_closure_with_one_cached_read(self):
        self.put('main.tex', r'\documentclass{article}\catcode`\%=\computed \input{one}')
        self.put('one.tex', r'ONE \input{two}\input{two}')
        self.put('two.tex', r'TWO \input{one}')
        reads = Counter()
        original = Path.read_bytes
        def read(path):
            reads[path.resolve()] += 1
            return original(path)
        with patch.object(Path, 'read_bytes', read):
            text, manifest, output, ledger = self.prepare()
        self.assertIn(r'\input{one}', text)
        self.assertEqual(set(manifest.code_inputs), {'one.tex', 'two.tex'})
        self.assertTrue((output / 'one.tex').is_file())
        self.assertTrue((output / 'two.tex').is_file())
        self.assertFalse(manifest.dependencies)
        self.assertTrue(all(reads[self.root / name] == 1 for name in manifest.source_reads))
        self.assertFalse([s for s in ledger.source_coverage if s['unaccounted']])

    def test_import_fallback_retains_the_original_search_context(self):
        self.put('main.tex', r'\documentclass{article}\usepackage{import}\import{parts/}{child.tex}\input{after}')
        self.put('parts/child.tex', r'\catcode`\%=\computed \input{grand}')
        self.put('parts/grand.tex', 'IMPORTED GRAND')
        self.put('grand.tex', 'WRONG GRAND')
        self.put('after.tex', 'AFTER')
        text, manifest, output, _ = self.prepare()
        self.assertIn(r'\import{parts/}{child.tex}', text)
        self.assertIn('AFTER', text)
        self.assertEqual((output / 'parts/grand.tex').read_text(), 'IMPORTED GRAND')
        self.assertNotIn('grand.tex', manifest.code_inputs)

    def test_full_project_survey_keeps_candidate_and_active_dependencies_distinct(self):
        self.put("main.tex", r"\documentclass{article}\input{live}")
        self.put("live.tex", "LIVE")
        self.put("unused.tex", r"\def\later{\input{latent}}\input{other}\catcode`\%=\computed \input{after}")
        self.put("after.tex", "AFTER")
        self.put("other.tex", "OTHER")
        text, manifest, _, _ = self.prepare()
        self.assertNotIn("OTHER", text)
        self.assertEqual([d["target"] for d in manifest.dependencies], ["live.tex"])
        report = next(r for r in manifest.source_survey if r["source"] == "unused.tex")
        self.assertEqual(report["status"], "observed")
        self.assertEqual(report["basis"], "independent_entry_profile")
        self.assertTrue(any(c["context"] == "stored_definition" and c["name"] == "input" for c in report["commands"]))
        self.assertTrue(any(c.get("arguments", {}).get("target") == {"literal": "other"} for c in report["commands"]))
        self.assertTrue(any(c["context"] == "after_reading_boundary" and c["name"] == "input" for c in report["commands"]))
        self.assertEqual({r["source"] for r in manifest.source_survey}, {"main.tex", "live.tex", "unused.tex", "after.tex", "other.tex"})

    def test_protected_groups_are_not_executed_but_later_input_is(self):
        opaque = r"\unknown*[note]{\input{missing}}"
        self.put("main.tex", r"\documentclass{article}" + opaque + r"\input{real}")
        self.put("real.tex", "REAL")
        text, manifest, _, _ = self.prepare()
        self.assertIn(opaque, text)
        self.assertIn("REAL", text)
        self.assertEqual(manifest.source_dependency_closure, "unresolved")
        self.assertTrue(any(r["reason"] == "deferred_dependency" and r["stage"] == "preparation" for r in manifest.requirements))

    def test_unreadable_unreferenced_source_is_reported_without_losing_master(self):
        self.put("main.tex", r"\documentclass{article}BODY")
        self.put("bad.sty", "").write_bytes(b"\xff")
        text, manifest, output, _ = self.prepare()
        self.assertIn("BODY", text)
        report = next(r for r in manifest.source_survey if r["source"] == "bad.sty")
        self.assertEqual(report["status"], "unreadable")
        self.assertIn("byte 0: ff", report["error"])
        self.assertIn("bad.sty", (output / "preparation.jsonl").read_text())

    def test_unbound_environment_keeps_fake_closers_inside_known_protected_syntax(self):
        environment = (r"\begin{unknown}\verb|\end{unknown}\input{fake}|"
                       r"\def\later{\end{unknown}\input{fake}}"
                       r"\textbf{\end{unknown}}\ordinary{\end{unknown}}"
                       r"\begin{verbatim}\end{unknown}\input{fake}\end{verbatim}\end{unknown}")
        self.put("main.tex", r"\documentclass{article}" + environment + r"\input{real}")
        self.put("real.tex", "REAL")
        text, manifest, _, _ = self.prepare()
        self.assertIn(environment, text)
        self.assertIn("REAL", text)
        self.assertEqual([d["target"] for d in manifest.dependencies], ["real.tex"])

    def test_computed_bibliography_and_citation_do_not_veto_output(self):
        self.put("main.tex", r"\documentclass{article}\cite{\key}\bibliography{refs}\input{tail}")
        self.put("refs.bib", "@misc{a,title={A}}")
        self.put("tail.tex", "TAIL")
        text, manifest, out, _ = self.prepare()
        self.assertNotIn(r"\bibitem{a}", text)
        self.assertIn("title={A}", (out / "bibliography.bib").read_text())
        self.assertEqual(manifest.bibliography.citation_discovery, "partial")
        self.assertIn("TAIL", text)
        self.put("main.tex", r"\documentclass{article}\bibliography{\refs}\input{tail}")
        text, manifest, _, _ = self.prepare()
        self.assertIn(r"\bibliography{\refs}", text)
        self.assertIn("TAIL", text)
        self.assertEqual(manifest.preparation_status, "partial")


class DispatcherContinuationTests(unittest.TestCase):
    def scan(self, text, preparation):
        resolver = BindingResolver()
        context = resolver.new_context()
        reader = TexReader(text, catcodes=context.catcodes, endline_char=context.endlinechar)
        items = list(StructuralDispatcher(reader, context, resolver, source_commands=True, preparation=preparation))
        return reader, items

    def test_strict_default_still_stops_and_preparation_has_explicit_unknown_coverage(self):
        text = r"\unknown{}\input{later}"
        _, strict = self.scan(text, False)
        self.assertIsInstance(strict[-1], ReadingBoundary)
        reader, items = self.scan(text, True)
        deferred = next(i for i in items if isinstance(i, DeferredRegion))
        self.assertEqual(text[deferred.span.start:deferred.span.end], r"\unknown{}")
        self.assertTrue(any(isinstance(i, SourceCommand) and i.action == "source_input" for i in items))
        coverage = ReadingCoverage(reader.basis, items)
        self.assertTrue(coverage.unknown.covers(deferred.span))
        self.assertEqual(coverage.deferred_regions, (deferred,))

    def test_math_and_literal_keep_exact_source_without_dispatching_inner_commands(self):
        text = "$$x + {\\input{latent}}% keep\n y$$" + r"\verb|\input{fake}|\input{real}"
        _, items = self.scan(text, True)
        self.assertEqual([i.value("target") for i in items if isinstance(i, SourceCommand)], ["real"])
        self.assertEqual(sum(isinstance(i, LiteralRegion) for i in items), 1)
        math = next(i for i in items if isinstance(i, DeferredRegion))
        self.assertEqual(text[math.span.start:math.span.end], "$$x + {\\input{latent}}% keep\n y$$")

    def test_inactive_literal_binding_does_not_expose_its_body_as_execution(self):
        _, items = self.scan(r"\Verb|\input{fake}|\input{later}", True)
        self.assertIsInstance(items[-1], ReadingBoundary)
        self.assertEqual(items[-1].reason, "package_not_loaded")
        self.assertFalse(any(isinstance(i, SourceCommand) for i in items))

    def test_inspecting_source_syntax_does_not_activate_a_package(self):
        resolver = BindingResolver()
        shape = resolver.source_command_syntax("includegraphics")
        self.assertEqual(shape.action, "asset_reference")
        self.assertEqual(resolver.active_packages, [])
        self.assertIsNone(resolver.source_command_syntax("Verb"))
        self.assertEqual(resolver.resolve_command("includegraphics").reason.value, "package_not_loaded")


if __name__ == "__main__":
    unittest.main()
