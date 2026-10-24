"""Regression cases for resolved effects, state restoration and policy handoff."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bindings.resolver import BindingResolver
from src.reading.contracts import EffectiveReadingProfile, UnresolvedBindingResult, UnresolvedReason
from src.reading.context import ReaderContext
from src.prepare.policy import load_policy
from src.reading.tex_reader import CatCode, TexReader, TokenKind


class ResolvedEffectTests(unittest.TestCase):
    def setUp(self):
        self.resolver = BindingResolver()

    def effective_codes(self, profile):
        context = self.resolver.new_context()
        context.apply_profile(profile)
        return context.catcodes

    def read_body(self, profile, source):
        self.assertIsInstance(profile, EffectiveReadingProfile)
        context = self.resolver.new_context()
        context.apply_profile(profile)
        return list(TexReader(source, catcodes=context.catcodes,
                              endline_char=context.endlinechar))

    def test_kernel_verbatim_keeps_percent_braces_backslashes_and_spaces(self):
        profile = self.resolver.resolve_environment("verbatim")
        tokens = self.read_body(profile, "  a% literal\n\\foo{b}")
        self.assertEqual("".join(t.value for t in tokens), "  a% literal\r\\foo{b}\r")
        self.assertFalse(any(t.kind == TokenKind.CONTROL_SEQUENCE for t in tokens))
        self.assertEqual([t.catcode for t in tokens[:2]], [CatCode.ACTIVE] * 2)
        self.assertTrue(profile.source_capture["preserve_raw_slice"])
        self.assertTrue(profile.tex_mechanics["trailing_spaces_stripped_by_input_ln"])

    def test_package_override_retains_literal_profile_defaults(self):
        self.resolver.load_package("verbatim")
        profile = self.resolver.resolve_environment("verbatim")
        tokens = self.read_body(profile, "x%y")
        self.assertEqual("".join(t.value for t in tokens), "x%y\r")
        self.assertEqual(profile.terminator.trailing_line_behavior, "discard_with_warning")
        self.assertTrue(profile.source_capture["preserve_raw_slice"])

    def test_inline_grammar_and_lexical_effects_survive_resolution(self):
        profile = self.resolver.resolve_command("verb")
        self.assertEqual(profile.grammar["control_sequence"], "verb")
        self.assertTrue(profile.grammar["star_token_allowed"])
        self.assertFalse(profile.grammar["multiline_allowed"])
        self.assertEqual(self.effective_codes(profile)["%"], CatCode.OTHER)
        starred = self.resolver.resolve_command(r"\verb*")
        self.assertTrue(starred.grammar["visible_spaces"])

    def test_custom_commandchars_only_enable_the_selected_characters(self):
        self.resolver.load_package("fancyvrb")
        profile = self.resolver.resolve_environment(
            "Verbatim", {"commandchars": ("!", "[", "]"), "commentchar": "%"})
        tokens = self.read_body(profile, "!foo[x]\\bar%ignored\nz")
        self.assertEqual([t.value for t in tokens if t.kind == TokenKind.CONTROL_SEQUENCE], ["foo"])
        self.assertEqual("".join(t.value for t in tokens), "foo[x]\\barz\r")
        self.assertEqual(self.effective_codes(profile)["["], CatCode.BEGIN_GROUP)
        self.assertEqual(self.effective_codes(profile)["\\"], CatCode.OTHER)
        self.assertEqual(profile.span_classification.category, "semi_verbatim_block")

    def test_option_disable_and_control_symbol_forms(self):
        self.resolver.load_package("fancyvrb")
        comment = self.resolver.resolve_environment("Verbatim", {"commentchar": r"\%"})
        self.assertEqual(self.effective_codes(comment)["%"], CatCode.COMMENT)
        disabled = self.resolver.resolve_environment(
            "Verbatim", {"commentchar": "none", "commandchars": "none"})
        self.assertEqual(self.effective_codes(disabled)["%"], CatCode.OTHER)
        self.assertEqual(self.effective_codes(disabled)["\\"], CatCode.OTHER)

    def test_unimplemented_and_unclassified_options_are_explicit(self):
        self.resolver.load_package("fancyvrb")
        for options in ({"codes": r"\catcode37=14"}, {"codes*": ""},
                        {"unknown": "anything"}, {"commandchars": ("!", "[", "[")},
                        {"commandchars": r"\ab"},
                        {"commandchars": ("!", "long", "]")}):
            with self.subTest(options=options):
                result = self.resolver.resolve_environment("Verbatim", options)
                self.assertIsInstance(result, UnresolvedBindingResult)
                self.assertEqual(result.reason, UnresolvedReason.UNSUPPORTED_READING_OPTION)
        # Options are interpreted only by their owning binding.
        result = self.resolver.resolve_environment("verbatim", {"commandchars": ("!", "[", "]")})
        self.assertIsInstance(result, UnresolvedBindingResult)

    def test_interpolation_is_an_explicit_plan_not_a_global_catcode_change(self):
        self.resolver.load_package("listings")
        profile = self.resolver.resolve_environment(
            "lstlisting", {"language": "Python", "escapeinside": "{(*@}{@*)}"})
        self.assertEqual(profile.family, "interpolated_verbatim_block")
        self.assertEqual(profile.span_classification.category, "interpolated_literal")
        self.assertEqual([(i.opening, i.closing, i.mode) for i in profile.interpolations],
                         [("(*@", "@*)", "tex")])
        with self.assertRaisesRegex(ValueError, "literal dispatcher"):
            self.resolver.new_context().apply_profile(profile)
        math = self.resolver.resolve_environment("lstlisting", {"mathescape": True})
        self.assertEqual(math.interpolations[0].mode, "math")
        plain = self.resolver.resolve_environment("lstlisting", {"mathescape": False})
        self.assertFalse(plain.interpolations)
        self.assertEqual(plain.span_classification.category, "opaque_literal")
        bad = self.resolver.resolve_environment("lstlisting", {"mathescape": "maybe"})
        self.assertIsInstance(bad, UnresolvedBindingResult)

    def test_interpolation_delimiters_do_not_lose_braces(self):
        self.resolver.load_package("listings")
        profile = self.resolver.resolve_environment("lstlisting", {"escapeinside": "{{x}}{y}"})
        self.assertEqual(profile.interpolations[0].opening, "{x}")
        for value in ("{x}{y}junk", "{x}", ("", "y"), ("x", 2)):
            result = self.resolver.resolve_environment("lstlisting", {"escapeinside": value})
            self.assertIsInstance(result, UnresolvedBindingResult)
        # Competing scanners require an ordering contract rather than an arbitrary choice.
        result = self.resolver.resolve_environment(
            "lstlisting", {"escapechar": "|", "mathescape": True})
        self.assertIsInstance(result, UnresolvedBindingResult)

    def test_external_package_commands_select_inlining_from_actual_role(self):
        policy = load_policy("prepare")
        for package, name in (("verbatim", r"\verbatiminput"),
                              ("fancyvrb", r"\VerbatimInput"), ("listings", r"\lstinputlisting")):
            with self.subTest(command=name):
                self.resolver.load_package(package)
                profile = self.resolver.resolve_command(name)
                self.assertIsInstance(profile, EffectiveReadingProfile)
                self.assertEqual(profile.action, "external_literal")
                self.assertEqual(profile.grammar["arguments"][-1], {"name": "target", "kind": "braced"})
                self.assertEqual(policy.get_role_action(profile.tex_mechanics["semantic_role"]), "inline")
                # The path is a normal TeX argument. Only its external body is literal.
                self.assertEqual(self.effective_codes(profile)["%"], CatCode.COMMENT)

    def test_policy_uses_semantic_role_without_losing_lexical_category(self):
        self.resolver.load_package("alltt")
        prose = load_policy(PROJECT_ROOT / "resources/experimental/policies/prose_extraction.yaml")
        for name in ("verbatim", "alltt"):
            profile = self.resolver.resolve_environment(name)
            self.assertEqual(prose.get_role_action(profile.span_classification.semantic_role),
                             "convert_to_markdown")
        profile = self.resolver.resolve_environment("alltt")
        self.assertEqual(profile.span_classification.category, "semi_verbatim_block")

    def test_pending_commands_do_not_become_successful_noops(self):
        pending = self.resolver.resolve_command(r"\catcode")
        self.assertIsInstance(pending, EffectiveReadingProfile)
        self.assertEqual(pending.grammar["handler"], "literal_catcode_assignment")
        with self.assertRaises(ValueError):
            self.resolver.new_context().apply_profile(pending)
        unloaded = self.resolver.resolve_command(r"\VerbatimInput")
        self.assertEqual(unloaded.reason, UnresolvedReason.PACKAGE_NOT_LOADED)
        self.resolver.load_package("listings")
        config = self.resolver.resolve_command(r"\lstset")
        self.assertIsInstance(config, EffectiveReadingProfile)
        self.assertEqual(config.action, "apply_configuration")
        with self.assertRaisesRegex(ValueError, "argument scanning"):
            self.resolver.new_context().apply_profile(config)

    def test_reloading_preserves_package_precedence(self):
        self.resolver.load_package("verbatim")
        self.resolver.load_package("comment")
        before = self.resolver.resolve_environment("comment")
        self.resolver.load_package("verbatim")
        after = self.resolver.resolve_environment("comment")
        self.assertEqual(self.resolver.active_packages, ["verbatim", "comment"])
        self.assertEqual(before, after)
        self.assertTrue(after.terminator.requires_column_zero)
        reverse = BindingResolver()
        reverse.load_package("comment")
        reverse.load_package("verbatim")
        self.assertFalse(reverse.resolve_environment("comment").terminator.requires_column_zero)

    def test_resolution_is_in_memory_and_results_do_not_mutate_registry(self):
        self.resolver.load_package("fancyvrb")
        with patch.object(Path, "open", side_effect=AssertionError("Unexpected file I/O")):
            first = self.resolver.resolve_environment("Verbatim", {"commentchar": "%"})
            first.catcode_overrides["%"] = CatCode.ESCAPE
            second = self.resolver.resolve_environment("Verbatim")
            self.assertEqual(self.effective_codes(second)["%"], CatCode.OTHER)
            self.resolver.resolve_command(r"\ExplSyntaxOn")


class StateRestorationTests(unittest.TestCase):
    def setUp(self):
        self.resolver = BindingResolver()
        self.on = self.resolver.resolve_command(r"\ExplSyntaxOn")
        self.off = self.resolver.resolve_command(r"\ExplSyntaxOff")
        self.context = self.resolver.new_context()

    def test_scoped_entry_does_not_leave_a_stale_guard(self):
        with self.context.lexical_scope():
            self.context.apply_profile(self.on)
        self.assertFalse(self.context.expl3_active)
        self.assertEqual(self.context.expl3_saved_catcodes, {})
        self.context.apply_profile(self.on)
        self.assertEqual(self.context.catcodes["_"], CatCode.LETTER)
        self.assertEqual(self.context.endlinechar, 32)

    def test_nested_exit_restores_outer_guard_and_original_baseline(self):
        self.context.catcodes[":"] = CatCode.ACTIVE
        self.context.apply_profile(self.on)
        with self.context.lexical_scope():
            self.context.apply_profile(self.off)
            self.context.catcodes[":"] = CatCode.OTHER
            self.context.apply_profile(self.on)
        self.assertTrue(self.context.expl3_active)
        self.context.apply_profile(self.off)
        self.assertEqual(self.context.catcodes[":"], CatCode.ACTIVE)

    def test_repeated_entry_reapplies_effects_without_overwriting_baseline(self):
        self.context.apply_profile(self.on)
        self.context.catcodes["_"] = CatCode.OTHER
        self.context.catcodes["@"] = CatCode.LETTER
        self.context.endlinechar = -1
        self.context.apply_profile(self.on)
        self.assertEqual(self.context.catcodes["_"], CatCode.LETTER)
        self.assertEqual(self.context.endlinechar, 32)
        self.context.apply_profile(self.off)
        self.assertEqual(self.context.catcodes["_"], CatCode.SUBSCRIPT)
        self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)
        self.assertEqual(self.context.endlinechar, 13)

    def test_scopes_keep_the_live_reader_table_and_restore_its_default(self):
        reader = TexReader("@@", catcodes=self.context.catcodes, endline_char=-1)
        original = reader.catcodes
        with self.context.lexical_scope():
            self.context.catcodes.default = CatCode.LETTER
            self.context.catcodes["@"] = CatCode.LETTER
            self.assertEqual(reader.next_token().catcode, CatCode.LETTER)
        self.assertIs(reader.catcodes, original)
        self.assertEqual(reader.next_token().catcode, CatCode.OTHER)
        self.assertEqual(reader.catcodes["é"], CatCode.OTHER)

    def test_context_copies_have_independent_scope_and_expl3_snapshots(self):
        self.context.push_scope()
        self.context.apply_profile(self.on)
        copied = self.context.copy()
        copied.apply_profile(self.off)
        copied.pop_scope()
        self.assertTrue(self.context.expl3_active)
        self.assertEqual(self.context.catcodes["_"], CatCode.LETTER)
        self.context.pop_scope()
        self.assertFalse(self.context.expl3_active)

    def test_group_tokens_are_dispatched_by_category_and_respect_execution_mode(self):
        begin = self.resolver.resolve_group(CatCode.BEGIN_GROUP)
        end = self.resolver.resolve_group(CatCode.END_GROUP)
        with self.context.argument_scanning():
            self.assertFalse(self.context.apply_profile(begin))
        self.assertFalse(self.context.pop_scope())
        self.context.apply_profile(begin)
        self.context.apply_profile(self.on)
        self.assertTrue(self.context.apply_profile(end))
        self.assertFalse(self.context.expl3_active)
        self.assertFalse(self.context.apply_profile(end))


if __name__ == "__main__":
    unittest.main()
