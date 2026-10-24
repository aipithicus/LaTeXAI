"""External resources through the production entry point, including provenance."""
from collections import Counter
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper


class ResourcePreparationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT.parents[1] / "temp/t/pytexml/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def prepare(self, body, packages="verbatim", **kwargs):
        self.put("main.tex", "\\documentclass{article}\n\\usepackage{" + packages + "}\n"
                 "\\begin{document}\n" + body + "\n\\end{document}\n")
        return preprocess_paper(str(self.root), **kwargs)

    def test_repeated_literal_keeps_exact_body_and_reads_file_once(self):
        body = "  # code\r\n% \\input{absent}\r\n  x = {1}\r\n"
        path = self.put("code/example.txt", body)
        reads = Counter()
        original = Path.read_bytes
        def read(source):
            reads[source.resolve()] += 1
            return original(source)
        with patch.object(Path, "read_bytes", read):
            text, manifest, out, ledger = self.prepare(
                r"\verbatiminput{code/example.txt} AFTER \verbatiminput*{code/example.txt}")
        self.assertEqual(text.count(body), 2)
        self.assertIn(r"\begin{verbatim*}", text)
        self.assertIn("AFTER", text)
        self.assertEqual(reads[path], 1)
        self.assertFalse((out / "code/example.txt").exists())
        self.assertEqual([r["disposition"] for r in manifest.resources], ["inlined", "inlined"])
        spans = [s for s in ledger.segments if s["source_file"] == "code/example.txt"]
        self.assertEqual(len({s["occurrence"] for s in spans}), 2)
        for span in spans:
            a, b = span["generated"]
            c, d = span["source"]
            self.assertEqual(text[a:b], body[c:d])

    def test_listing_options_and_safe_delimiter_fallback(self):
        self.put("snippet.py", "print('hello')\n")
        text, manifest, _, _ = self.prepare(r"\lstinputlisting[language=Python,caption={A,B}]{snippet.py}", "listings")
        self.assertIn("\\begin{lstlisting}[language=Python,caption={A,B}]\nprint('hello')", text)
        self.assertEqual(manifest.resources[0]["disposition"], "inlined")
        body = "hello\n\\end{verbatim}\nworld"
        self.put("collision.txt", body)
        text, manifest, out, _ = self.prepare(r"\verbatiminput{collision.txt} AFTER")
        self.assertIn(r"\verbatiminput{literal-resources/collision.txt}", text)
        self.assertIn("AFTER", text)
        self.assertEqual((out / "literal-resources/collision.txt").read_text(), body)
        self.assertEqual(manifest.requirements[-1]["reason"], "literal_terminator_collision")

    def test_reading_options_retain_one_resource_and_continue(self):
        self.put("code.txt", "x $y$\n")
        text, manifest, out, _ = self.prepare(r"\lstinputlisting[mathescape=true]{code.txt} AFTER", "listings")
        self.assertIn("literal-resources/code.txt", text)
        self.assertTrue((out / "literal-resources/code.txt").is_file())
        self.assertIn("AFTER", text)
        self.assertEqual(manifest.resources[0]["disposition"], "retained")

    def test_active_option_key_is_not_assumed_to_be_formatting(self):
        self.put("code.txt", "BODY\n")
        text, manifest, out, _ = self.prepare(r"\catcode`\!=13 \lstinputlisting[!]{code.txt} AFTER", "listings")
        self.assertIn("AFTER", text)
        self.assertTrue((out / "literal-resources/code.txt").is_file())
        self.assertEqual(manifest.resources[0]["disposition"], "retained")
        self.assertTrue(any(r["reason"] == "computed_option" for r in manifest.requirements))

    def test_definitions_literals_and_skipped_branches_do_not_read_external_files(self):
        text, manifest, _, _ = self.prepare(
            r"\def\later{\verbatiminput{absent}}\iffalse\verbatiminput{also-absent}\fi" +
            "\n\\verb|\\verbatiminput{not-a-file}| AFTER")
        self.assertIn("AFTER", text)
        self.assertEqual(manifest.resources, [])

    def test_policy_removes_comment_span_and_preserves_listing_bytes(self):
        listing = "\\begin{lstlisting}[language=Python]\r\n% \\input{missing}  \r\n\\end{lstlisting}\r\n"
        text, manifest, _, ledger = self.prepare(
            "BEFORE\n\\begin{comment}\n\\input{absent}\n\\end{comment}\n" + listing + "AFTER",
            "comment,listings")
        self.assertNotIn("absent", text)
        self.assertNotIn(r"\begin{comment}", text)
        self.assertIn(listing, text)
        self.assertIn("AFTER", text)
        self.assertFalse(manifest.unresolved)
        self.assertTrue(any("author_notes" in t.reason for t in ledger.tombstones))

    def test_retained_style_boundary_does_not_block_later_inputs(self):
        style = r"\makeatletter{\def\input#1{WRONG}\newif\ifdraft \catcode\unknown=11 \input{unresolved}}"
        self.put("local.sty", style)
        self.put("tail.tex", "TAIL % removed\n")
        text, manifest, out, _ = self.prepare(r"\input{tail} AFTER", "local")
        self.assertIn("TAIL", text)
        self.assertNotIn("removed", text)
        self.assertIn("AFTER", text)
        self.assertEqual((out / "local.sty").read_text(), style)
        self.assertEqual(manifest.preparation_status, "partial")
        self.assertTrue(any(r["reason"] == "retained_code_reading" for r in manifest.requirements))
        self.assertEqual(manifest.preserved_source_spans, [])

    def test_literal_catcode_effect_crosses_input_and_scope_restores(self):
        self.put("cat.tex", "\\catcode`\\%=12 \n")
        text, manifest, _, _ = self.prepare("{\\input{cat}%ordinary\n} X% removed\nAFTER")
        self.assertIn("%ordinary", text)
        self.assertNotIn("removed", text)
        self.assertIn("AFTER", text)
        self.assertFalse(manifest.unresolved)

    def test_factories_hide_excluded_dependencies_and_replay_included_body_in_memory(self):
        self.put("child.tex", "CHILD % removed\n")
        body = ("\\excludecomment{draft}\n\\includecomment{shown}\n"
                "\\begin{draft}\n\\input{absent}\n\\end{draft}\n"
                "\\begin{shown} discarded opening suffix\n"
                "\\makeatletter\n\\input{child}\n{\n"
                "\\end{shown}\nAFTER}\n\\foo@bar\n")
        text, manifest, _, ledger = self.prepare(body, "comment")
        self.assertIn("CHILD", text)
        self.assertIn("AFTER", text)
        self.assertIn(r"\foo@bar", text)
        for excluded in ("absent", "discarded opening suffix", "removed", r"\begin{shown}", r"\end{shown}"):
            self.assertNotIn(excluded, text)
        self.assertFalse(manifest.unresolved)
        self.assertEqual(manifest.source_reads.count("child.tex"), 1)
        self.assertEqual(ledger.master_length, len(text))
        source = (self.root / "main.tex").read_text()
        for segment in ledger.segments:
            if segment["operation"] == "IDENTITY" and segment["source_file"] == "main.tex":
                a, b = segment["generated"]
                c, d = segment["source"]
                self.assertEqual(text[a:b], source[c:d])

    def test_fancy_factory_regex_escapes_name_and_registers_starred_variant(self):
        body = ("\\DefineVerbatimEnvironment{code+}{Verbatim}{numbers=left}\n"
                "\\begin{code+}\n% \\input{absent}\n\\end {code+}\n"
                "\\begin{code+*}\n{x}  \n\\end{code+*}\nAFTER")
        text, manifest, _, _ = self.prepare(body, "fancyvrb")
        self.assertIn("% \\input{absent}", text)
        self.assertIn("{x}  \n", text)
        self.assertIn("AFTER", text)
        self.assertFalse(manifest.unresolved)

    def test_factory_scopes_restore_outer_meaning(self):
        body = ("\\includecomment{region}\n{\\excludecomment{region}\n"
                "\\begin{region}\nHIDDEN\n\\end{region}\n}\n"
                "\\begin{region}\nVISIBLE\n\\end{region}\nAFTER")
        text, manifest, _, _ = self.prepare(body, "comment")
        self.assertNotIn("HIDDEN", text)
        self.assertIn("VISIBLE", text)
        self.assertIn("AFTER", text)
        self.assertFalse(manifest.unresolved)

    def test_replay_failure_preserves_whole_original_wrapper(self):
        block = "\\begin{shown}\nBEFORE\n\\catcode37=\\unknown\nAFTER\n\\end{shown}\n"
        text, manifest, _, _ = self.prepare("\\includecomment{shown}\n" + block, "comment")
        self.assertIn(block, text)
        self.assertEqual(text.count("BEFORE"), 1)
        self.assertEqual(manifest.preparation_status, "partial")

    def test_image_width_expression_does_not_block_literal_filename(self):
        self.put("plot.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"/>')
        text, manifest, out, _ = self.prepare(r"\includegraphics[width=0.5\linewidth]{plot.svg} AFTER", "graphicx")
        self.assertIn(r"\includegraphics[width=0.5\linewidth]{plot.svg}", text)
        self.assertEqual([i.rel_path for i in manifest.active_images], ["plot.svg"])
        self.assertTrue((out / "plot.svg").is_file())
        self.assertFalse(manifest.unresolved)

    def test_conflicting_bibliography_is_retained_in_payload_without_vetoing_master(self):
        self.put("one.bib", "@misc{key,title={FIRST}}")
        self.put("two.bib", "@misc{key,title={SECOND}}")
        text, manifest, out, _ = self.prepare(r"\cite{key}\bibliography{one,two} AFTER")
        self.assertIn("AFTER", text)
        self.assertIn(r"\bibliography{bibliography}", text)
        canonical = (out / "bibliography.bib").read_text()
        self.assertIn("FIRST", canonical)
        self.assertIn("SECOND", canonical)
        self.assertEqual(manifest.bibliography.preparation_backend, "deferred-conflict")
        self.assertEqual(manifest.preparation_status, "partial")
        self.assertFalse((out / "bibliography.bbl").exists())


if __name__ == "__main__":
    unittest.main()
