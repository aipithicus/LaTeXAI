import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.validation.tex_trace import parse, differences


class TraceTests(unittest.TestCase):
    def test_commands_macro_calls_and_math_paths_stay_separate(self):
        log = "\n".join(["PYTEXML:BEGIN", r"{vertical mode: \count}", r"{\number}",
            r"\wrap #1->#1", "#1<-A", r"> \box0=", r"\hbox(2.0+0.0)x3.0", r".\f A", "! OK.",
            "### math mode entered at line 1", r"\mathord", r".\fam1 x", r"^\fam0 2", r"_\fam0 1",
            "! OK.", "PYTEXML:END"])
        r = parse(log, expected_ok=2)
        self.assertEqual([c["command"] for c in r["commands"]], [r"\count", r"\number"])
        self.assertEqual(r["macro_calls"][0]["header"], r"\wrap #1")
        self.assertEqual(r["boxes"][0]["nodes"][0]["children"][0]["text"], r"\f A")
        self.assertEqual([n["path"] for n in r["lists"][0]["nodes"][0]["children"]], [".", "^", "_"])
        self.assertEqual(differences({"width": 2}, {"width": 3})[0]["path"], "/width")

    def test_missing_markers_errors_and_truncated_lists_are_not_passes(self):
        for log in ("! Undefined control sequence.", "PYTEXML:BEGIN", "PYTEXML:BEGIN\nPYTEXML:END\n! OK."):
            with self.assertRaises(ValueError):
                parse(log)
        with self.assertRaises(ValueError):
            parse("PYTEXML:BEGIN\n> \\box0=\n\\hbox(0.0+0.0)x0.0\n.etc.\n! OK.\nPYTEXML:END", expected_ok=1)


if __name__ == "__main__":
    unittest.main()
