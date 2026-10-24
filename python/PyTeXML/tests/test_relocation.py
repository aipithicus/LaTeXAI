"""Relocation needs a readable PDF AND a local filesystem dependency receipt."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.validation.render import RenderConfig
from src.validation.relocation import audit_dependencies, qualify_relocation


class RelocationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.prepared = self.root / "prepared"
        self.prepared.mkdir()
        (self.prepared / "master.tex").write_text(r"\documentclass{article}\begin{document}Hello\end{document}")
        self.raw = self.root / "raw"
        self.raw.mkdir()
        (self.raw / "main.tex").write_text("RAW SOURCE MUST NOT BE USED")
        self.config = RenderConfig(Path(sys.executable), timeout_seconds=7)

    def compiler(self, command, **kwargs):
        self.assertIn("--hide", command)
        self.assertIn(str(self.raw / "main.tex"), command)
        self.assertNotIn("TEXINPUTS", kwargs["env"])
        entry = Path(command[-1])
        self.assertNotIn("RAW SOURCE", entry.read_text())
        build = Path(command[command.index("--outdir") + 1])
        with pymupdf.open() as doc:
            doc.new_page().insert_text((10, 20), "Hello")
            doc.save(build / "master.pdf")
        rules = Path(command[command.index("--makefile-rules") + 1])
        rules.write_text(f"{build / 'master.pdf'} : {entry}\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    def test_isolated_payload_and_raw_hide_with_dependency_proof(self):
        with patch.dict(os.environ, {"TEXINPUTS": str(self.raw)}), patch(
                "src.validation.render.subprocess.run", side_effect=self.compiler):
            report = qualify_relocation(self.prepared, self.root / "result", self.config, raw_dirs=[self.raw])
        self.assertEqual(report["status"], "qualified")
        self.assertFalse(report["raw_source_staged"])
        self.assertEqual(report["hidden_raw_files"], 1)
        self.assertTrue((self.raw / "main.tex").is_file())
        self.assertFalse(any(p.is_dir() for p in (self.root / "result").iterdir()))

    def test_successful_pdf_with_missing_or_external_receipt_is_not_qualified(self):
        for mode in ("missing", "external"):
            def compiler(command, **kwargs):
                result = self.compiler(command, **kwargs)
                rules = Path(command[command.index("--makefile-rules") + 1])
                if mode == "missing":
                    rules.unlink()
                else:
                    rules.write_text(f"master.pdf : {self.raw / 'main.tex'}\n")
                return result
            with self.subTest(mode=mode), patch("src.validation.render.subprocess.run", side_effect=compiler):
                report = qualify_relocation(self.prepared, self.root / mode, self.config, raw_dirs=[self.raw])
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["render"]["status"], "unqualified")

    def test_receipt_escaped_spaces_and_traversal_are_checked(self):
        stage = self.root / "stage"
        stage.mkdir()
        (stage / "master.tex").write_text("master")
        (stage / "figures").mkdir()
        (stage / "figures/a b.pdf").write_bytes(b"fixture")
        rules = self.root / "inputs.mk"
        rules.write_text("master.pdf : master.tex \\\n figures/a\\ b.pdf\n")
        result = audit_dependencies(rules, stage, stage, self.root / "build")
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["inputs"][1]["path"], "figures/a b.pdf")
        rules.write_text("master.pdf : ../raw/main.tex\n")
        self.assertEqual(audit_dependencies(rules, stage, stage, self.root / "build")["status"], "external_dependencies")

    def test_outdir_rebased_receipts_require_a_real_staged_file(self):
        build = self.root / "build"
        build.mkdir()
        rules = build / "inputs.mk"
        rules.write_text(f"master.pdf : {build / 'local.sty'}\n")
        self.assertEqual(audit_dependencies(rules, self.prepared, self.prepared, build)["status"], "unresolved_receipt")
        (self.prepared / "local.sty").write_text("LOCAL")
        result = audit_dependencies(rules, self.prepared, self.prepared, build)
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["inputs"], [{"path": "local.sty", "role": "payload_or_driver"}])

    def test_xdv_compilation_is_reported_separately_from_pdf_rendering(self):
        def compiler(command, **kwargs):
            self.assertEqual(command[command.index("--outfmt") + 1], "xdv")
            entry = Path(command[-1])
            build = Path(command[command.index("--outdir") + 1])
            (build / "master.xdv").write_bytes(b"\xf7\x07XDV fixture")
            Path(command[command.index("--makefile-rules") + 1]).write_text(f"master.xdv : {entry}\n")
            return subprocess.CompletedProcess(command, 0)
        with patch("src.validation.render.subprocess.run", side_effect=compiler):
            report = qualify_relocation(self.prepared, self.root / "xdv", self.config, output_format="xdv")
        self.assertEqual(report["status"], "qualified")
        self.assertEqual(report["render"]["status"], "compiled")
        self.assertIsNone(report["render"]["pdf"])
        self.assertFalse(list((self.root / "xdv").glob("*.xdv")))

    @unittest.skipUnless(os.environ.get("PYTEXML_TEST_TECTONIC"), "explicit optional compiler not configured")
    def test_live_relocated_payload_survives_deleted_disposable_raw_tree(self):
        # Delete only this test's disposable raw file/directory. Production
        # qualification never renames or deletes the user's raw specimens.
        (self.raw / "main.tex").unlink()
        self.raw.rmdir()
        fonts = os.environ.get("PYTEXML_TEST_FONT_DIR")
        config = RenderConfig(Path(os.environ["PYTEXML_TEST_TECTONIC"]),
                              font_dirs=(Path(fonts),) if fonts else ())
        report = qualify_relocation(self.prepared, self.root / "live", config)
        self.assertEqual(report["status"], "qualified", report)


if __name__ == "__main__":
    unittest.main()
