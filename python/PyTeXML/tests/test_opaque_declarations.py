"""Declaration signatures fence stored code without simulating definitions/hooks."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper
from src.bindings.resolver import BindingResolver
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader
from src.reading.contracts import SourceCommand


class OpaqueDeclarationTests(unittest.TestCase):
    def test_declarations_do_not_install_targets_or_execute_body_effects(self):
        bodies = [r"\providecommand*\iflater[1][\iffalse]{\newif\ifinner\innertrue\catcode`\%=12 #1}",
                  r"\renewenvironment{later}[1][\iftrue]{\newif\ifinner\innertrue}{\catcode`\%=12}",
                  r"\AtBeginDocument{\newif\ifinner\innertrue\catcode`\%=12}"]
        for body in bodies:
            with self.subTest(body=body):
                resolver = BindingResolver()
                context = resolver.new_context()
                reader = TexReader(body, catcodes=context.catcodes, endline_char=context.endlinechar)
                dispatcher = StructuralDispatcher(reader, context, resolver, source_commands=True, preparation=True)
                items = list(dispatcher)
                command = next(i for i in items if isinstance(i, SourceCommand))
                self.assertEqual(command.action, "opaque")
                self.assertEqual(body[command.span.start:command.span.end], body)
                self.assertIsNone(context.lookup_meaning("iflater"))
                self.assertIsNone(context.lookup_meaning("ifinner"))
                self.assertEqual(int(context.catcodes["%"]), 14)
                self.assertEqual(dispatcher.decisions, [])

    def test_prepare_preserves_bodies_and_continues_known_boolean_routing(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            blocks = (r"\providecommand{\later}{\flagtrue\iffalse\input{not_reached}\fi}"
                      r"\renewenvironment{later}{\flagtrue}{\flagtrue}"
                      r"\AtBeginDocument{\flagtrue}")
            source = r"\documentclass{article}\newif\ifflag" + blocks + r"\ifflag BAD\else GOOD\fi\input{tail}"
            (root / "main.tex").write_text(source, encoding="utf-8")
            (root / "tail.tex").write_text("TAIL", encoding="utf-8")
            text, manifest, _, _ = preprocess_paper(str(root), root_tex="main.tex")
            self.assertIn(blocks, text)
            self.assertIn("GOOD", text)
            self.assertIn("TAIL", text)
            self.assertNotIn(" BAD", text)
            self.assertFalse(any(d.get("target") == "not_reached.tex" for d in manifest.dependencies))
            stored = [r for r in manifest.requirements if r["reason"] == "deferred_dependency"]
            self.assertTrue(stored)
            self.assertTrue(all(r["activity"] == "stored" and r["next_step"] == "macro_invocation" for r in stored))


if __name__ == "__main__":
    unittest.main()
