"""Global meaning writes, local restoration and frozen definition tokens."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import DeferredRegion, ReadingBoundary, StoredDefinition, UncertainMeaning
from src.reading.definition_scanner import DefinitionScanner
from src.reading.dispatcher import StructuralDispatcher
from src.reading.effect_summary import EffectSummary, NameSet
from src.reading.effects import definition_summary
from src.reading.tex_reader import CatCode, TexReader, TokenKind


class GlobalDefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()
        cls.oracle = json.loads((Path(__file__).parent / "fixtures/engine/global-definitions.expected.json").read_text())

    def host(self, text, *, preparation=False):
        knowledge = BindingResolver(self.catalog)
        context = knowledge.new_context()
        reader = TexReader(text, source_id="globals.tex", catcodes=context.catcodes,
                           endline_char=context.endlinechar)
        return StructuralDispatcher(reader, context, knowledge,
                                    preparation=preparation, source_commands=preparation)

    def read(self, text, **kwargs):
        host = self.host(text, **kwargs)
        items = list(host)
        self.assertFalse([i for i in items if isinstance(i, ReadingBoundary)], items)
        return host, items

    def value(self, host, name, kind=TokenKind.CONTROL_SEQUENCE):
        definition = host.context.lookup_definition(name, kind)
        self.assertIsInstance(definition, StoredDefinition)
        return "".join(t.value for t in definition.replacement_tokens)

    def observed_macro(self, name):
        return self.oracle[name].removeprefix("macro:->")

    def test_global_write_survives_all_enclosing_groups_and_later_local_writes(self):
        host, _ = self.read(
            r"\def\a{OLD}{\def\a{OUTER}{\def\a{INNER}\gdef\a{GLOBAL}"
            r"\def\a{LOCAL}\xdef\inside{\a}}\xdef\middle{\a}}\xdef\after{\a}")
        self.assertEqual([self.value(host, n) for n in ("inside", "middle", "after", "a")],
                         [self.observed_macro(n) for n in ("inside", "middle", "after", "after")])
        self.assertEqual(host.context.scope_depth, 0)

    def test_global_orderings_and_absent_targets(self):
        for body, expected in (
                (r"{\gdef\a{G}}", "G"),
                (r"{\def\a{L}\gdef\a{G}}", "G"),
                (r"{\gdef\a{G}\def\a{L}}", "G"),
                (r"{\gdef\a{FIRST}{\gdef\a{LAST}\def\a{L}}\def\a{OUTER}}", "LAST")):
            with self.subTest(body=body):
                host, _ = self.read(body)
                self.assertEqual(self.value(host, "a"), expected)

    def test_global_write_does_not_disturb_other_names_or_local_let_copies(self):
        host, _ = self.read(
            r"\def\a{OLD}\def\b{OTHER}{\def\b{LOCAL}\gdef\a{GLOBAL}\let\a\b}")
        self.assertEqual(self.value(host, "a"), "GLOBAL")
        self.assertEqual(self.value(host, "b"), self.observed_macro("b"))

    def test_xdef_expands_old_target_then_publishes_globally(self):
        host, _ = self.read(r"\def\a{OLD}{\def\a{LOCAL}\xdef\a{\a NEW}}\edef\after{\a}")
        self.assertEqual(self.value(host, "a"), self.observed_macro("expanded"))
        self.assertEqual(self.value(host, "after"), self.observed_macro("expanded"))
        self.assertEqual([t.value for t in host.context.lookup_definition("a").body_tokens],
                         ["a", "N", "E", "W"])

    def test_copied_global_primitive_keeps_scope_after_original_is_shadowed(self):
        host, _ = self.read(r"\let\save\gdef\def\gdef{SHADOW}{\save\a{G}}")
        self.assertEqual(self.value(host, "a"), "G")
        self.assertEqual(self.value(host, "gdef"), "SHADOW")

    def test_scanner_captures_global_definition_without_applying_scope(self):
        host = self.host(r"\gdef\a{G}")
        token = host.reader.next_token()
        definition = DefinitionScanner(host.reader, host.context).primitive(token.span.start)
        self.assertEqual("".join(t.value for t in definition.body_tokens), "G")
        self.assertIsNone(host.context.lookup_meaning("a"))

    def test_failed_global_definition_preserves_local_value_and_outer_journal(self):
        for failed in (r"\gdef\a{missing", r"\xdef\a{\unknown}"):
            with self.subTest(failed=failed):
                host = self.host(r"\def\a{OLD}{\def\a{LOCAL}" + failed)
                items = list(host)
                self.assertIsInstance(items[-1], ReadingBoundary)
                self.assertEqual(self.value(host, "a"), "LOCAL")
                host.context.pop_scope()
                self.assertEqual(self.value(host, "a"), "OLD")

    def test_context_checkpoint_restores_journals_after_global_write(self):
        host = self.host(r"\def\a{OLD}{\def\a{LOCAL}")
        for _ in range(3):
            self.assertNotIsInstance(host.next_item(), ReadingBoundary)
        self.assertEqual(self.value(host, "a"), "LOCAL")
        checkpoint = host.context.copy()
        donor, _ = self.read(r"\gdef\a{G}")
        host.context.record_definition(donor.context.lookup_definition("a"), global_=True)
        fork = host.context.copy()
        fork.pop_scope()
        self.assertEqual("".join(t.value for t in fork.lookup_definition("a").replacement_tokens), "G")
        host.context.restore_from(checkpoint)
        self.assertEqual(self.value(host, "a"), "LOCAL")
        host.context.pop_scope()
        self.assertEqual(self.value(host, "a"), "OLD")
        self.assertEqual(checkpoint.scope_depth, 1)

    def test_global_definition_retains_t13_category_after_lexical_restoration(self):
        host, _ = self.read(r"\begingroup\catcode`\_=12 \gdef\under{_}\endgroup")
        token, = host.context.lookup_definition("under").body_tokens
        self.assertEqual(token.catcode, CatCode.OTHER)
        self.assertEqual(self.value(host, "under"), self.observed_macro("under"))
        self.assertEqual(token.catcode.name.lower(), self.oracle["underscore_token"])
        self.assertEqual(str(int(host.context.catcodes["_"])), self.oracle["underscore_after"])

    def test_t14_remapped_braces_remain_other_tokens_after_group_exit(self):
        host, _ = self.read(
            r"\begingroup\catcode`\(=1 \catcode`\)=2 \catcode`\{=12 \catcode`\}=12 "
            r"\gdef\left({)\gdef\right(})\endgroup")
        for name, character in (("left", "{"), ("right", "}")):
            token, = host.context.lookup_definition(name).body_tokens
            self.assertEqual((token.value, token.catcode), (character, CatCode.OTHER))
            self.assertEqual(token.value, self.observed_macro(name))
            self.assertEqual(token.catcode.name.lower(), self.oracle[name + "_token"])
        self.assertEqual(str(int(host.context.catcodes["{"])), self.oracle["brace_after"])
        self.assertEqual(host.context.catcodes["("], CatCode.OTHER)

    def test_active_target_and_same_spelled_control_symbol_are_independent(self):
        host, _ = self.read(r"\begingroup\catcode`\!=13 \gdef!{ACTIVE}\endgroup\def\!{SYMBOL}")
        self.assertEqual(self.value(host, "!", TokenKind.ACTIVE_CHARACTER), self.observed_macro("active"))
        self.assertEqual(self.value(host, "!"), self.observed_macro("symbol"))
        self.assertEqual(str(int(host.context.catcodes["!"])), self.oracle["exclamation_after"])

    def test_observational_global_summary_invalidates_without_installing_body(self):
        host, _ = self.read(r"\def\a{OLD}\def\paint{\gdef\a{G}}", preparation=True)
        definition = host.context.lookup_definition("paint")
        effect = definition_summary(definition, host.context, host.knowledge)
        self.assertTrue(effect.selective)
        self.assertEqual(effect.scope, "global")
        local, _ = self.read(r"\def\a{LOCAL}")
        host.context.push_scope()
        host.context.record_definition(local.context.lookup_definition("a"))
        host.defer_effects(definition.span, summary=effect)
        host.context.pop_scope()
        self.assertIsInstance(host.context.lookup_meaning("a"), UncertainMeaning)

    def test_explicit_global_definition_reestablishes_an_uncertain_target_only(self):
        host, _ = self.read(r"\def\a{OLD}\def\b{OTHER}")
        span = host.context.lookup_definition("a").span
        host.context.push_scope()
        host.context.invalidate_writes(EffectSummary(scope="global", meanings=NameSet(("a", "b"))), span)
        donor, _ = self.read(r"\gdef\a{G}")
        host.context.record_definition(donor.context.lookup_definition("a"), global_=True)
        host.context.pop_scope()
        self.assertEqual(self.value(host, "a"), "G")
        self.assertIsInstance(host.context.lookup_meaning("b"), UncertainMeaning)

    def test_skipped_global_definition_does_not_publish(self):
        host, _ = self.read(r"\def\a{OLD}\iffalse\gdef\a{WRONG}\fi")
        self.assertEqual(self.value(host, "a"), "OLD")

    def test_globaldefs_and_global_prefix_still_stop_before_assignment(self):
        for source in (r"\globaldefs=-1\gdef\a{G}", r"\global\def\a{G}"):
            with self.subTest(source=source):
                host = self.host(source)
                boundary = host.next_item()
                self.assertIsInstance(boundary, ReadingBoundary)
                self.assertEqual(boundary.reason, "unsupported_primitive" if source.startswith(r"\globaldefs") else "assignment_prefix")
                self.assertIsNone(host.context.lookup_meaning("a"))

    def test_global_loader_defined_in_child_group_is_used_after_return(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "main.tex").write_text(
            r"\documentclass{article}{\input{defs}}\load\begin{document}BODY\end{document}", encoding="utf-8")
        child = r"\gdef\load{\RequirePackage{natbib}}" + "\n"
        (root / "defs.tex").write_text(child, encoding="utf-8")
        text, manifest, _, ledger = preprocess_paper(str(root))
        self.assertIn(r"\gdef\load{\RequirePackage{natbib}}", text)
        self.assertIn(r"\load", text)
        self.assertTrue(any(p.name == "natbib" and p.binding_activated for p in manifest.packages_declared))
        self.assertEqual(manifest.unresolved, [])
        self.assertEqual(ledger.master_length, len(text))


if __name__ == "__main__":
    unittest.main()
