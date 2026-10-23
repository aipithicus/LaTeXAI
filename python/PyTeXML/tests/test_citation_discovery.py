"""Citation observation is independent of full package interpretation."""
from collections import Counter
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.resolver import BindingResolver
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import DeferredRegion, SourceCommand, ReadingBoundary
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader


class CitationDiscoveryTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT.parents[1] / "temp/t/pytexml/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def prepare(self, body, preamble=""):
        self.put("main.tex", "\\documentclass{article}\n" + preamble +
                 "\n\\begin{document}\n" + body + "\n\\end{document}\n")
        return preprocess_paper(str(self.root))

    def test_split_databases_pending_style_and_late_citations_use_cached_source(self):
        # A local style cannot yet execute its boolean option setup. Its pending
        # provider must not prevent observational reading of the citep grammar.
        style = "\\newif\\if@refs\\if@refs\\RequirePackage{natbib}\\fi\n"
        self.put("local.sty", style)
        one = "@misc{first,title={FIRST},custom={enrichment}}\n@misc{unused,title={A}}\n"
        two = "@misc{second,title={SECOND}}\n@misc{late,title={LATE}}\n@misc{unused,title={B}}\n"
        self.put("one.bib", one)
        self.put("two.bib", two)
        self.put("part.tex", r"\citep*[see {a[b]}][p.~2]{second,first}")
        reads = Counter()
        original = Path.read_bytes
        def read(path):
            reads[path.resolve()] += 1
            return original(path)
        with patch.object(Path, "read_bytes", read):
            text, manifest, out, ledger = self.prepare(
                r"\cite{first}\input{part}\input{part}\bibliography{one,two}\Citet{late}",
                r"\usepackage{local}")
        self.assertEqual(manifest.bibliography.citation_keys, ["first", "second", "late"])
        for key in ("first", "second", "late"):
            self.assertEqual(text.count(r"\bibitem{" + key + "}"), 1)
        self.assertNotIn(r"\bibitem{unused}", text)
        self.assertNotIn(r"\bibliography{", text)
        self.assertEqual((out / "bibliography.bib").read_text(), one + "\n" + two)
        self.assertIn((out / "bibliography.bbl").read_text(), text)
        self.assertEqual((out / "local.sty").read_text(), style)
        self.assertEqual(manifest.bibliography.preparation_backend, "native-bibtex")
        self.assertEqual(manifest.bibliography.citation_discovery, "partial")
        pending = [g for g in manifest.bibliography.citation_gaps if g["reason"] == "citation_binding_pending"]
        self.assertEqual(len(pending), 3)
        self.assertEqual({g["binding"] for g in pending}, {"packages/natbib"})
        self.assertNotIn("natbib", {p.name for p in manifest.packages_declared})
        self.assertFalse(any(d["reason"] == "bibliography_conflict" for d in manifest.unresolved))
        self.assertTrue(all(reads[self.root / name] == 1 for name in manifest.source_reads))
        self.assertEqual(ledger.master_length, len(text))

    def test_active_natbib_captures_stars_notes_and_capitalized_forms(self):
        commands = ["cite", "citep", "citet", "Citep", "Citet", "citealt", "citealp", "Citealt", "Citealp"]
        self.put("refs.bib", "\n".join("@misc{k%d,title={T%d}}" % (i, i) for i in range(len(commands))))
        body = " ".join("\\" + name + "*[before {x[y]}][after]{k%d}" % i for i, name in enumerate(commands))
        text, manifest, _, _ = self.prepare(body + r"\bibliography{refs}", r"\usepackage{natbib}")
        self.assertEqual(manifest.bibliography.citations_count, len(commands))
        self.assertEqual(manifest.bibliography.citation_discovery, "complete")
        self.assertEqual(manifest.bibliography.citation_gaps, [])
        self.assertIn(body, text)

    def test_comments_literals_skipped_text_and_stored_definitions_are_not_citations(self):
        self.put("refs.bib", "@misc{real,title={REAL}}\n@misc{fake,title={FAKE}}")
        body = ("% \\citep{missing}\n" + r"\verb|\citep{missing}|"
                r"\begin{verbatim}\citep{missing}\end{verbatim}"
                r"\iffalse\citep{missing}\fi\def\unused{\citep{fake}}"
                r"\citep{real}\bibliography{refs}")
        text, manifest, _, _ = self.prepare(body, r"\usepackage{natbib}")
        self.assertEqual(manifest.bibliography.citation_keys, ["real"])
        self.assertNotIn(r"\bibitem{fake}", text)
        self.assertEqual(manifest.bibliography.citation_discovery, "complete")

    def test_author_redefinition_is_not_treated_as_a_package_citation(self):
        self.put("refs.bib", "@misc{real,title={REAL}}")
        text, manifest, _, _ = self.prepare(
            r"\def\citep#1{#1}\citep{not-a-key}\cite{real}\bibliography{refs}",
            r"\usepackage{natbib}")
        self.assertEqual(manifest.bibliography.citation_keys, ["real"])
        self.assertIn(r"\citep{not-a-key}", text)
        self.assertEqual(manifest.bibliography.citation_discovery, "partial")

    def test_nested_citation_is_located_without_executing_its_owner(self):
        self.put("refs.bib", "@misc{real,title={REAL}}\n@misc{nested,title={NESTED}}")
        text, manifest, out, _ = self.prepare(
            r"\cite{real}\footnote{\citep{nested}}\bibliography{refs}", r"\usepackage{natbib}")
        self.assertEqual(manifest.bibliography.citation_keys, ["real"])
        self.assertTrue(any(g["reason"] == "nested_citation" for g in manifest.bibliography.citation_gaps))
        self.assertNotIn(r"\bibitem{nested}", text)
        self.assertIn("NESTED", (out / "bibliography.bib").read_text())

    def test_unrelated_math_and_package_requirements_do_not_select_unused_conflicts(self):
        self.put("refs.bib", "@misc{real,title={REAL}}\n@misc{unused,title={A}}\n@misc{unused,title={B}}")
        text, manifest, out, _ = self.prepare(
            r"$x+y$\cite{real}\bibliography{refs}", r"\usepackage{notyetbound}")
        self.assertEqual(manifest.dependency_closure, "unresolved")
        self.assertEqual(manifest.bibliography.citation_discovery, "complete")
        self.assertEqual(manifest.bibliography.citations_count, 1)
        self.assertIn(r"\bibitem{real}", text)
        self.assertNotIn(r"\bibitem{unused}", text)
        self.assertIn("title={B}", (out / "bibliography.bib").read_text())

    def test_only_explicit_nocite_wildcard_selects_every_entry(self):
        self.put("refs.bib", "@misc{a,title={A}}\n@misc{b,title={B}}")
        for citation, expected in [(r"\nocite{*}", 2), (r"\cite{*}", 0), (r"\cite{\computed}", 0), ("", 0)]:
            with self.subTest(citation=citation):
                text, manifest, out, _ = self.prepare(citation + r"\bibliography{refs}")
                self.assertEqual(text.count(r"\bibitem{"), expected)
                self.assertEqual(manifest.bibliography.citations_count, expected)
                self.assertIn("title={B}", (out / "bibliography.bib").read_text())

    def test_partial_source_read_retains_database_without_inventing_citations(self):
        self.put("refs.bib", "@misc{known,title={KNOWN}}\n@misc{later,title={LATER}}")
        text, manifest, out, _ = self.prepare(
            r"\cite{known}\bibliography{refs}\catcode`\%=\computed \cite{later}")
        self.assertEqual(manifest.bibliography.citation_keys, ["known"])
        self.assertTrue(any(g["reason"] == "unread_source" for g in manifest.bibliography.citation_gaps))
        self.assertIn(r"\cite{later}", text)
        self.assertNotIn(r"\bibitem{later}", text)
        self.assertIn("LATER", (out / "bibliography.bib").read_text())

    def test_missing_unconfirmed_key_does_not_become_a_false_resource_error(self):
        self.put("refs.bib", "@misc{known,title={KNOWN}}")
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    self.put("main.bbl", r"\begin{thebibliography}{1}\bibitem{known}KNOWN\end{thebibliography}")
                text, manifest, _, _ = self.prepare(r"\cite{known}\citep{unconfirmed}\bibliography{refs}")
                self.assertIn(r"\bibitem{known}", text)
                self.assertIn(r"\citep{unconfirmed}", text)
                self.assertNotIn(r"\bibitem{unconfirmed}", text)
                self.assertTrue(any("Unconfirmed citation key 'unconfirmed'" in warning
                                    for warning in manifest.bibliography.preparation_warnings))


class CitationGrammarTests(unittest.TestCase):
    def test_inactive_syntax_preserves_header_and_does_not_activate_package(self):
        source = r"\citep*[see][p.~2]{one,two} TAIL"
        resolver = BindingResolver()
        context = resolver.new_context()
        reader = TexReader(source, catcodes=context.catcodes, endline_char=context.endlinechar)
        items = list(StructuralDispatcher(reader, context, resolver, source_commands=True, preparation=True))
        header = items[0]
        self.assertIsInstance(header, DeferredRegion)
        self.assertEqual(header.command.value("keys"), "one,two")
        self.assertEqual(header.command.value("note"), "see")
        note = header.command.argument("second_note").span
        self.assertEqual(source[note.start:note.end], "p.~2")
        self.assertEqual(header.binding_id, "packages/natbib")
        self.assertEqual(source[header.span.start:header.span.end], r"\citep*[see][p.~2]{one,two}")
        self.assertFalse(resolver.is_package_active("natbib"))
        self.assertFalse(any(isinstance(item, (ReadingBoundary, SourceCommand)) for item in items))


if __name__ == "__main__":
    unittest.main()
