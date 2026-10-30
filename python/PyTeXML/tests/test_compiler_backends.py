"""Native compiler identity and reruns are independent evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.validation.compilers import BACKENDS, compile_document, probe_profile
from src.validation.render import RenderConfig, compiler_environment, render_comparison
from src.validation.assessment import summarize


class CompilerBackendTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "main.tex"
        self.source.write_text(r"\relax\end", encoding="ascii")
        self.config = RenderConfig(Path(sys.executable), backend="pdftex", engine_profile="pdftex")

    def test_native_command_disables_shell_and_rejects_unimplemented_closure_audit(self):
        command = BACKENDS["pdftex"].command(self.config, self.source, self.root, "pdf")
        self.assertIn("-no-shell-escape", command)
        self.assertIn("-recorder", command)
        self.assertEqual(command[-1], str(self.source))
        with self.assertRaisesRegex(ValueError, "closure auditing"):
            BACKENDS["pdftex"].command(self.config, self.source, self.root, "xdv")
        with self.assertRaisesRegex(ValueError, "closure auditing"):
            BACKENDS["pdftex"].command(self.config, self.source, self.root, "pdf", self.root / "rules")

    def test_native_reruns_until_auxiliary_state_is_stable(self):
        aux = self.root / "main.aux"
        def run(*args, **kwargs):
            aux.write_text("stable", encoding="ascii")
            return subprocess.CompletedProcess(args[0], 0)
        with patch("src.validation.compilers.subprocess.run", side_effect=run) as native:
            _, passes, converged = compile_document(self.config, self.source, self.root,
                self.root / "run.log", {}, "pdf")
        self.assertTrue(converged)
        self.assertEqual(len(passes), 2)
        self.assertLessEqual(native.call_args.kwargs["timeout"], self.config.timeout_seconds)

    def test_unstable_auxiliary_state_does_not_claim_convergence(self):
        count = 0
        def run(*args, **kwargs):
            nonlocal count
            count += 1
            (self.root / "main.aux").write_text(str(count), encoding="ascii")
            return subprocess.CompletedProcess(args[0], 0)
        with patch("src.validation.compilers.subprocess.run", side_effect=run):
            _, passes, converged = compile_document(self.config, self.source, self.root,
                self.root / "run.log", {}, "pdf")
        self.assertFalse(converged)
        self.assertEqual(len(passes), 4)

    def test_profile_probe_observes_absence_and_does_not_mask_primitives(self):
        transcript = b"\n".join(b"PYTEXML-PROFILE " + name + b"=" + value for name, value in [
            (b"eTeXversion", b"present"), (b"expanded", b"present"), (b"pdfoutput", b"present"),
            (b"ifpdfabsnum", b"absent"),
            (b"XeTeXversion", b"absent"), (b"luatexversion", b"absent"), (b"directlua", b"absent")])
        with patch("src.validation.compilers.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0, transcript, b"")):
            report = probe_profile(RenderConfig(Path(sys.executable), engine_profile="etex"), self.root, {})
        self.assertEqual(report["status"], "mismatch")
        self.assertEqual(report["mismatches"], {"pdfoutput": {"expected": False, "observed": True}})
        self.assertNotIn(r"\let\pdfoutput", (self.root / "profile-probe.tex").read_text())

    @unittest.skipUnless(os.environ.get("PYTEXML_TEST_NATIVE_DIR"), "explicit native tool directory not configured")
    def test_live_pdf_and_dvi_adapters_and_profile_evidence(self):
        native = Path(os.environ["PYTEXML_TEST_NATIVE_DIR"])
        for backend, executable, profile, status in (
            ("pdftex", "pdflatex.exe", "pdftex", "rendered"),
            ("etex", "latex.exe", "etex", "profile_mismatch"),
        ):
            with self.subTest(backend=backend):
                original, prepared = self.root / (backend + "-source"), self.root / (backend + "-prepared")
                original.mkdir(); prepared.mkdir()
                document = r"\documentclass{article}\begin{document}Profile witness.\end{document}"
                (original / "main.tex").write_text(document, encoding="ascii")
                (prepared / "master.tex").write_text(document, encoding="ascii")
                (prepared / "manifest.json").write_text(json.dumps({"engine_profile": {"name": profile}}))
                config = RenderConfig(native / executable, backend=backend, dvipdfmx=native / "dvipdfmx.exe")
                report = render_comparison(original, "main.tex", prepared, self.root / (backend + "-report"), config)
                self.assertEqual(report["status"], status, report)
                self.assertEqual(report["prepared"]["status"], "rendered", report)
                self.assertTrue(report["temporary_inputs_removed"])
                if backend == "etex":
                    self.assertEqual(summarize(report)["classification"], "PROFILE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
