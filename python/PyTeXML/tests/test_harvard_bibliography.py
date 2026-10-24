"""natbib's Harvard-compatible BBL grammar uses the shared argument reader.

Grammar evidence: natbib.dtx, the definition of harvarditem[4][], and the
package manual's Harvard-family section. No TeX compiler is needed by these tests.
"""
from collections import Counter
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.resolver import BindingResolver
from src.prepare.bibliography import BibliographyPreparationError
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import DeferredRegion, ReadingBoundary, SourceCommand
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader


class HarvardBibliographyTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def put(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def read(self, text, *, active=True):
        resolver = BindingResolver()
        if active:
            resolver.load_package("natbib")
        context = resolver.new_context()
        reader = TexReader(text, catcodes=context.catcodes, endline_char=context.endlinechar)
        return resolver, list(StructuralDispatcher(reader, context, resolver, source_commands=True, preparation=True))

    def prepare(self, body, bbl, *, extra=""):
        self.put("main.tex", r"\documentclass{article}\usepackage{natbib}" + extra +
                 r"\begin{document}" + body + r"\end{document}")
        self.put("main.bbl", "\\begin{thebibliography}{99}\n" + bbl + "\n\\end{thebibliography}\n")
        with patch("subprocess.run", side_effect=AssertionError("Preparation cannot invoke a compiler")):
            return preprocess_paper(str(self.root))

    def test_header_grammar_preserves_optional_nested_and_multiline_arguments(self):
        examples = [
            (r"\harvarditem{Full Authors}{1991}{key}", None),
            (r"\harvarditem[]{Full Authors}{1991}{key}", ""),
            (r"\harvarditem[{Short [name]}]{Full {Authors} \harvardand\ Other}{19{91}}{key}", "{Short [name]}"),
            ("\\harvarditem[Short]%\n {Full \\textit{Authors}}\n {1991}%\n {key}", "Short"),
        ]
        for header, short in examples:
            with self.subTest(header=header):
                _, items = self.read(header + " BODY")
                self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))
                command = items[0]
                self.assertIsInstance(command, SourceCommand)
                self.assertEqual(command.metadata["bibliography_key"], "key")
                self.assertEqual(command.value("key"), "key")
                self.assertEqual(command.argument("short_authors") is not None, short is not None)
                if short is not None:
                    arg = command.argument("short_authors")
                    self.assertEqual(header[arg.span.start:arg.span.end], short)
                self.assertEqual(header[command.span.start:command.span.end], header)

    def test_inactive_provider_supplies_only_provisional_syntax(self):
        header = r"\harvarditem[Short]{Full}{2020}{key}"
        resolver, items = self.read(header, active=False)
        self.assertIsInstance(items[0], DeferredRegion)
        self.assertEqual(items[0].binding_id, "packages/natbib")
        self.assertEqual(items[0].command.value("key"), "key")
        self.assertFalse(resolver.is_package_active("natbib"))

    def test_existing_bbl_is_inlined_with_all_keys_and_canonical_enrichment(self):
        refs = "@misc{first,title={FIRST},custom={retain me}}\n@misc{second,title={SECOND}}\n"
        self.put("refs.bib", refs)
        self.put("part.tex", r"\citep{first}")
        headers = [r"\harvarditem{Full \harvardand\ Other}{1991}{first}",
                   r"\harvarditem[Short]{Full {Second}}{2020}{second}"]
        bbl = headers[0] + " FIRST.\n" + headers[1] + " SECOND."
        reads = Counter()
        original = Path.read_bytes

        def read_bytes(path):
            reads[path.resolve()] += 1
            return original(path)

        with patch.object(Path, "read_bytes", read_bytes):
            text, manifest, out, ledger = self.prepare(
                r"\input{part}\input{part}\bibliographystyle{agsm}\bibliography{refs}\citet{second}", bbl)
        self.assertEqual(manifest.bibliography.preparation_backend, "existing-bbl")
        self.assertEqual(manifest.bibliography.citations_count, 2)
        self.assertEqual(manifest.bibliography.citation_keys, ["first", "second"])
        self.assertNotIn(r"\bibliography{", text)
        self.assertNotIn(r"\bibliographystyle{", text)
        for header in headers:
            self.assertEqual(text.count(header), 1)
        self.assertIn((out / "bibliography.bbl").read_text(), text)
        self.assertEqual((out / "bibliography.bib").read_text(), refs)
        self.assertEqual(ledger.master_length, len(text))
        self.assertTrue(all(reads[self.root / name] == 1 for name in manifest.source_reads))
        self.assertIn(bbl, (self.root / "main.bbl").read_text())

    def test_existing_harvard_and_standard_entries_can_mix_without_a_database(self):
        bbl = r"\harvarditem{Author}{2000}{one}ONE.\bibitem[Label]{two}TWO."
        text, manifest, out, _ = self.prepare(r"\citep{one,two}\bibliography{absent}", bbl)
        self.assertEqual(manifest.bibliography.citations_count, 2)
        self.assertIsNone(manifest.bibliography.canonical_bib)
        self.assertFalse((out / "bibliography.bib").exists())
        self.assertIn(bbl, text)

    def test_protected_and_skipped_headers_do_not_supply_missing_keys(self):
        fake = r"\harvarditem[Missing]{Missing}{1999}{missing}"
        protected = ["% " + fake + "\n", r"\verb|" + fake + "|",
                     r"\begin{verbatim}" + fake + r"\end{verbatim}",
                     r"\def\stored{" + fake + "}", r"\iffalse" + fake + r"\fi"]
        for region in protected:
            with self.subTest(region=region), self.assertRaisesRegex(BibliographyPreparationError, "missing"):
                self.prepare(r"\cite{missing}\bibliography{absent}", region)
        self.assertFalse((self.root / "extracted/master.tex").exists())

    def test_author_redefinition_shadows_the_entry_binding(self):
        with self.assertRaisesRegex(BibliographyPreparationError, "missing"):
            self.prepare(r"\cite{missing}\bibliography{absent}",
                         r"\harvarditem{Author}{2000}{missing}", extra=r"\def\harvarditem#1#2#3{}")

    def test_missing_citation_is_not_confused_with_author_or_year_arguments(self):
        with self.assertRaisesRegex(BibliographyPreparationError, "missing"):
            self.prepare(r"\cite{missing}\bibliography{absent}",
                         r"\harvarditem[missing]{missing}{missing}{different}BODY")


if __name__ == "__main__":
    unittest.main()
