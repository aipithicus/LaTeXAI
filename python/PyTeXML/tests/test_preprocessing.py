"""Bounded preparation regressions; run with Python unittest discovery."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.bibliography import BibliographyPreparationError
from src.bibtex import Database, BibTeXError
from src.prepare.bibliography import extraction_bbl
from src.prepare.assets import batch_convert_assets_to_svg, AssetUse
from src.assets import raster_to_svg_wrapper
from src.prepare.session import PreparationSession, PreparationUnresolved
from src.prepare.pipeline import preprocess_paper
from src.prepare.discovery import find_root_tex
from src.prepare.inventory import preflight_inventory
from src.assets import characterize_image
from src.source_io import SourceDecodingError, invalid_utf8_spans, open_source


class PreparationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT_ROOT / "temp" / "tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def document(self, body="Body", name="main.tex"):
        return self.put(name, "\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}\n")

    def flatten(self, name="main.tex"):
        session = PreparationSession(self.root, root_tex=name).run()
        return "".join(piece.text for piece in session.pieces)

    def test_repeated_inputs_are_distinct_occurrences(self):
        self.document("\\input{part}\n\\input{part}")
        self.put("part.tex", "REPEATED BODY\n")
        self.assertEqual(self.flatten().count("REPEATED BODY"), 2)

    def test_cycle_is_explicit_and_a_new_run_is_independent(self):
        self.document(r"\input{part}")
        self.put("part.tex", "\\input{main}\n")
        with self.assertRaisesRegex(PreparationUnresolved, "input_cycle"):
            preprocess_paper(str(self.root))
        self.put("part.tex", "Recovered")
        text, _, _, _ = preprocess_paper(str(self.root))
        self.assertIn("Recovered", text)

    def test_import_decode_failure_is_logged(self):
        self.document(r"\usepackage{import}\subimport{sections}{part}")
        self.put("sections/part.tex", "").write_bytes(b"\xff")
        with self.assertRaises(SourceDecodingError):
            preprocess_paper(str(self.root))
        self.assertIn("sections", (self.root / "extracted/preparation.log").read_text())

    def test_nested_discovered_and_explicit_roots(self):
        self.document(name="src/paper.tex")
        self.assertEqual(find_root_tex(str(self.root)), "src/paper.tex")
        manifest = preflight_inventory(str(self.root), root_tex="src/paper.tex", execute_probe=False)
        self.assertEqual(manifest.root_file, "src/paper.tex")
        text, _, _, _ = preprocess_paper(str(self.root), root_tex="src/paper.tex")
        self.assertIn("Body", text)

    def test_nested_magic_root_retains_directory(self):
        self.put("hint.tex", "% !TEX root = src/paper.tex\n")
        self.document(name="src/paper.tex")
        self.assertEqual(find_root_tex(str(self.root)), "src/paper.tex")

    def test_preflight_inventory_is_pure_python_without_subprocess(self):
        self.document(name="src/paper.tex")
        manifest = preflight_inventory(str(self.root), root_tex="src/paper.tex")
        self.assertEqual(manifest.root_file, "src/paper.tex")
        self.assertEqual(manifest.engine, "pytexml")

    def test_default_output_never_becomes_a_root(self):
        self.document(name="extracted/master.tex")
        with self.assertRaises(FileNotFoundError):
            find_root_tex(str(self.root))

    def test_custom_output_excluded_from_discovery_and_reruns(self):
        self.document(name="src/paper.tex")
        self.document("OLD OUTPUT", name="canonical/main.tex")
        output = self.root / "canonical"
        for _ in range(2):
            text, manifest, _, _ = preprocess_paper(str(self.root), output_dir=str(output))
            self.assertEqual(manifest.root_file, "src/paper.tex")
            self.assertNotIn("OLD OUTPUT", text)
            self.assertFalse(any(x.startswith("canonical/") for x in manifest.active_tex_files + manifest.dormant_tex_files))

    def test_output_cannot_replace_source_directory(self):
        self.document()
        with self.assertRaises(ValueError):
            preprocess_paper(str(self.root), output_dir=str(self.root))

    def test_missing_bbl_is_not_deleted_by_inliner(self):
        self.document("\\cite{key}\n\\bibliographystyle{plain}\n\\bibliography{refs}")
        self.assertIn("\\bibliography{refs}", self.flatten())
        self.assertIn("\\bibliographystyle{plain}", self.flatten())

    def bib_project(self, existing=True, database=True):
        self.document("\\cite{key}\n\\bibliographystyle{plain}\nBefore \\bibliography{refs} After")
        if database:
            self.put("refs.bib", '@article{key, author={Alice Author}, title={Original title}, journal={Journal}, year={2024}, customfield={Enrichment}}\n')
        if existing:
            self.put("main.bbl", "\\begin{thebibliography}{1}\n\\bibitem{key} Alice Author. Original title.\n\\end{thebibliography}\n")

    def test_existing_bbl_is_embedded_and_metadata_is_local(self):
        self.bib_project()
        text, manifest, output, _ = preprocess_paper(str(self.root))
        self.assertIn("\\bibitem{key}", text)
        self.assertIn("Before", text)
        self.assertIn("After", text)
        self.assertNotIn("\\bibliography{", text)
        self.assertNotIn("\\bibliographystyle", text)
        self.assertIn("customfield={Enrichment}", (output / "bibliography.bib").read_text())
        self.assertEqual(manifest.bibliography.prepared_bbl, "bibliography.bbl")
        self.assertEqual(manifest.entrypoint, "master.tex")
        self.assertEqual(json.loads((output / "manifest.json").read_text())["entrypoint"], "master.tex")
        self.assertEqual(manifest.bibliography.preparation_backend, "existing-bbl")

    def test_existing_bbl_does_not_require_original_database(self):
        self.bib_project(database=False)
        text, manifest, _, _ = preprocess_paper(str(self.root))
        self.assertIn("\\bibitem{key}", text)
        self.assertIsNone(manifest.bibliography.canonical_bib)

    def test_unresolved_citations_fail_without_publishing_master(self):
        self.bib_project()
        self.put("main.bbl", "\\begin{thebibliography}{1}\n\\bibitem{other} Wrong entry.\n\\end{thebibliography}\n")
        with self.assertRaisesRegex(BibliographyPreparationError, "key"):
            preprocess_paper(str(self.root))
        self.assertFalse((self.root / "extracted/master.tex").exists())
        self.assertIn("FAILED", (self.root / "extracted/preparation.log").read_text())

    def test_native_bibliography_never_invokes_a_compiler(self):
        self.bib_project(existing=False)
        with patch("subprocess.run", side_effect=AssertionError("Unexpected compiler invocation")):
            text, manifest, output, _ = preprocess_paper(str(self.root))
        self.assertIn("\\bibitem{key}", text)
        self.assertIn("Original title", text)
        self.assertIn("customfield", text)
        self.assertEqual(manifest.bibliography.preparation_backend, "native-bibtex")
        self.assertTrue((output / "bibliography.bbl").is_file())
        self.assertTrue((output / "bibliography.bib").is_file())
        self.assertNotIn("\\bibliography{", text)

    def test_preflight_compiler_probe_is_not_called(self):
        self.document()
        manifest = preflight_inventory(str(self.root))
        self.assertIsNotNone(manifest)

    def test_native_bibliography_needs_no_publisher_style(self):
        self.document("\\cite{key}\n\\bibliography{refs}")
        self.put("refs.bib", "@misc{key,title={Content}}")
        text, _, _, _ = preprocess_paper(str(self.root))
        self.assertIn("Content", text)

    def test_nested_bbl_uses_nested_root(self):
        self.document("\\cite{key}\n\\bibliographystyle{plain}\n\\bibliography{refs}", "src/paper.tex")
        self.put("src/paper.bbl", "\\begin{thebibliography}{1}\n\\bibitem{key} Nested.\n\\end{thebibliography}\n")
        text, manifest, _, _ = preprocess_paper(str(self.root))
        self.assertIn("Nested.", text)
        self.assertEqual(manifest.bibliography.preparation_backend, "existing-bbl")

    def test_biblatex_data_is_not_pasted_as_formatted_text(self):
        self.document("\\addbibresource{refs.bib}\n\\printbibliography")
        text, manifest, _, _ = preprocess_paper(str(self.root))
        self.assertIn("\\addbibresource{refs.bib}", text)
        self.assertIn("\\printbibliography", text)
        self.assertNotIn("thebibliography", text)
        self.assertEqual(manifest.preparation_status, "partial")
        self.assertEqual(manifest.unresolved[0]["reason"], "bibliography_formatter")

    def test_bibliography_commands_in_literals_are_not_prepared(self):
        self.document(r"\verb|\bibliography{absent}|")
        text, _, _, _ = preprocess_paper(str(self.root))
        self.assertIn(r"\verb|\bibliography{absent}|", text)

    def test_source_decoding_failure_is_logged_with_byte_offset(self):
        self.document()
        (self.root / "main.tex").write_bytes(b"\\documentclass{article}\n\xff\n")
        with self.assertRaises(SourceDecodingError):
            preprocess_paper(str(self.root))
        log = (self.root / "extracted/preparation.log").read_text()
        self.assertIn("main.tex", log)
        self.assertIn("byte 24", log)
        self.assertFalse((self.root / "extracted/master.tex").exists())

    def test_encoding_scan_preserves_offsets_after_multibyte_characters(self):
        raw = "é α".encode("utf-8") + b"\xff\xfe\r\nX\x80Y\xe2\x82"
        self.assertEqual(invalid_utf8_spans(raw), [(5, b"\xff\xfe"), (10, b"\x80"), (12, b"\xe2\x82")])
        path = self.put("malformed.tex", "")
        path.write_bytes(raw)
        with self.assertRaisesRegex(SourceDecodingError, "byte 5: ff fe; byte 10: 80; byte 12: e2 82"):
            open_source(path)

    def test_valid_unicode_and_literal_spelling_are_not_scrubbed(self):
        source = "García α e\u0301 \u200b\u2060\ufeff \\verb|e\u0301\u200b|\n"
        path = self.put("unicode.tex", source)
        self.assertEqual(open_source(path).read(), source)
        self.assertEqual(invalid_utf8_spans(source.encode("utf-8")), [])

    def test_bibliography_decoding_failure_is_not_swallowed(self):
        self.bib_project()
        (self.root / "main.bbl").write_bytes(b"\xff")
        with self.assertRaises(SourceDecodingError):
            preprocess_paper(str(self.root))
        self.assertIn("main.bbl", (self.root / "extracted/preparation.log").read_text())

    def test_local_style_decoding_failure_is_logged(self):
        self.document("\\usepackage{customstyle}")
        self.put("customstyle.sty", "").write_bytes(b"\xff")
        with self.assertRaises(SourceDecodingError):
            preprocess_paper(str(self.root))
        self.assertIn("customstyle.sty", (self.root / "extracted/preparation.log").read_text())

    def test_conversion_failure_is_logged_without_master_or_raw_copy(self):
        self.document("\\usepackage{graphicx}\\includegraphics{bad.png}")
        self.put("bad.png", "invalid image")
        with self.assertRaises(RuntimeError):
            preprocess_paper(str(self.root))
        out = self.root / "extracted"
        self.assertIn("bad.png", (out / "preparation.log").read_text())
        self.assertFalse((out / "master.tex").exists())
        self.assertFalse((out / "bad.png").exists())

    def test_unknown_dimensions_are_reported(self):
        image = self.root / "bad.png"
        image.write_bytes(b"not an image")
        info = characterize_image("bad.png", str(image))
        self.assertIsNone(info.width)
        self.assertIsNone(info.height)
        self.assertIn("Dimensions unavailable", info.dimension_error)
        with self.assertRaises(RuntimeError):
            raster_to_svg_wrapper(image, self.root / "bad.svg")
        self.assertFalse((self.root / "bad.svg").exists())

    def test_missing_pillow_never_fabricates_dimensions(self):
        with patch("src.assets.Image", None):
            with self.assertRaisesRegex(RuntimeError, "Pillow"):
                raster_to_svg_wrapper(self.root / "anything.png", self.root / "anything.svg")

    def test_unsupported_asset_fails_without_original_copy(self):
        asset = self.put("image.unknown", "DATA")
        out = self.root / "extracted"
        out.mkdir()
        with self.assertRaises(RuntimeError):
            batch_convert_assets_to_svg([AssetUse(None, asset)], out, self.root)
        self.assertEqual(list(out.iterdir()), [])

    def test_nested_conditionals_preserve_only_executed_text(self):
        self.document(r"A\iftrue B\iffalse C\fi D\else E\fi F")
        text, _, _, _ = preprocess_paper(str(self.root))
        self.assertIn("B", text)
        self.assertIn("D", text)
        self.assertNotIn(" E", text)
        self.assertNotIn(" C", text)
        self.assertIn("F", text)

    def test_native_reader_handles_nested_values_strings_and_preambles(self):
        db = Database()
        db.read(r'''% @article{ignored, invalid}
@comment{ignored @article{alsoignored}}
@string{prefix = "A "}
@string{joined = prefix # {nested {Title}}}
@preamble{"\providecommand{\noop}[1]{#1}"}
@article(key,
 title = joined # { with $x_{i}$},
 author = {de la Cruz, Ana and {Research Team}},
 note = "Quoted {\"o} and {nested {braces}}",
 month = jan,
 year = 2024,
 strangefield = {Untouched},
 url = {https://example.org/a_b?q=1&v=20%25},
)''')
        fields = {name: value.resolve() for name, value in db.entries["key"][0].fields}
        self.assertEqual(fields["title"], "A nested {Title} with $x_{i}$")
        self.assertEqual(fields["author"], "de la Cruz, Ana and {Research Team}")
        self.assertEqual(fields["month"], "January")
        self.assertEqual(fields["strangefield"], "Untouched")
        bbl = extraction_bbl(db, ["key"])
        self.assertIn(r"\providecommand{\noop}[1]{#1}", bbl)
        self.assertIn(r"\url{https://example.org/a_b?q=1&v=20%25}", bbl)

    def test_native_reader_shares_strings_across_declared_databases(self):
        self.document("\\cite{key}\n\\bibliography{strings,refs}")
        self.put("strings.bib", '@string{journalname="Shared Journal"}')
        self.put("refs.bib", '@article{key,title={Title},journal=journalname}')
        text, _, out, _ = preprocess_paper(str(self.root))
        self.assertIn("Shared Journal", text)
        self.assertIn("@string", (out / "bibliography.bib").read_text())

    def test_repeated_fields_are_preserved_and_reported(self):
        self.document("\\cite{key}\n\\bibliography{refs}")
        self.put("refs.bib", "@misc{key,title={Title},note={One},note={Two}}")
        text, manifest, out, _ = preprocess_paper(str(self.root))
        self.assertIn("{One}", text)
        self.assertIn("{Two}", text)
        self.assertIn("Repeated field", manifest.bibliography.preparation_warnings[0])
        self.assertIn("Repeated field", (out / "preparation.log").read_text())

    def test_undefined_strings_only_block_selected_content(self):
        db = Database()
        db.read('@string{bad = missing # { suffix}} @misc{a,title=bad} @misc{b,title={Good}}')
        self.assertIn("Good", extraction_bbl(db, ["b"]))
        self.assertIn("Undefined", db.diagnostics[0])
        with self.assertRaisesRegex(BibTeXError, "Undefined"):
            extraction_bbl(db, ["a"])

    def test_missing_native_entry_is_an_explicit_failure(self):
        self.bib_project(existing=False)
        self.put("refs.bib", "@misc{other,title={Other}}")
        with self.assertRaisesRegex(BibliographyPreparationError, "key"):
            preprocess_paper(str(self.root))
        self.assertFalse((self.root / "extracted/master.tex").exists())


if __name__ == "__main__":
    unittest.main()
