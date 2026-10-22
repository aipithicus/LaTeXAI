"""
Behavioral and Integration Conformance Tests for Binding Resolution & Execution Context.

Tests source examples, reader effects, state transitions, option resolution,
and boundary matching against binding declarations.
"""

from pathlib import Path
import re
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bindings.resolver import BindingResolver
from src.reading.contracts import EffectiveReadingProfile, UnresolvedBindingResult, UnresolvedReason
from src.reading.context import ExecutionMode, ReaderContext
from src.reading.tex_reader import (
    CatCode,
    CatcodeTable,
    ReaderState,
    TexReader,
    TokenKind,
)


class BindingResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = BindingResolver()

    def test_mouth_profiles_loaded(self):
        expected = [
            "raw_block", "discard_block", "semi_verbatim_block",
            "interpolated_verbatim_block", "inline_delimited",
            "inline_braced", "latex_ascii"
        ]
        for name in expected:
            self.assertIn(name, self.resolver.catalog.profiles)

    def test_default_engine_verbatim_resolution(self):
        profile = self.resolver.resolve_environment("verbatim")
        self.assertIsInstance(profile, EffectiveReadingProfile)
        self.assertEqual(profile.name, "verbatim")
        self.assertEqual(profile.family, "raw_block")
        self.assertIsNotNone(profile.terminator)
        # Kernel verbatim: exact match without whitespace
        self.assertEqual(profile.terminator.exact_string, r"\end{verbatim}")
        self.assertEqual(profile.terminator.regex_pattern, r"\\end\{verbatim\}")
        self.assertEqual(profile.terminator.trailing_line_behavior, "preserve_trailing_content")

    def test_package_override_verbatim_resolution(self):
        self.resolver.load_package("verbatim")
        profile = self.resolver.resolve_environment("verbatim")
        self.assertIsInstance(profile, EffectiveReadingProfile)
        self.assertEqual(profile.terminator.matching_domain, "physical_line")
        # Package allows horizontal space in \end {verbatim}
        self.assertEqual(profile.terminator.regex_pattern, r"\\end[ \t]*\{verbatim\}")
        # Package discards remainder of line after terminator
        self.assertEqual(profile.terminator.trailing_line_behavior, "discard_with_warning")

    def test_comment_package_requires_package_load(self):
        # Before loading comment package
        res = self.resolver.resolve_environment("comment")
        self.assertIsInstance(res, UnresolvedBindingResult)
        self.assertEqual(res.reason, UnresolvedReason.PACKAGE_NOT_LOADED)

        # After loading comment package
        self.resolver.load_package("comment")
        profile = self.resolver.resolve_environment("comment")
        self.assertIsInstance(profile, EffectiveReadingProfile)
        self.assertEqual(profile.terminator.matching_domain, "physical_line")
        self.assertTrue(profile.terminator.requires_column_zero)
        self.assertFalse(profile.terminator.trailing_content_allowed)
        self.assertEqual(profile.terminator.regex_pattern, r"^\\end\{comment\}$")

    def test_alltt_preserves_trailing_line_and_recognizes_commands(self):
        self.resolver.load_package("alltt")
        profile = self.resolver.resolve_environment("alltt")
        self.assertIsInstance(profile, EffectiveReadingProfile)
        self.assertEqual(profile.terminator.boundary_mode, "command_boundary")
        self.assertEqual(profile.terminator.trailing_line_behavior, "preserve_trailing_content")
        # \ and {} are NOT in catcode_overrides, so they retain escape and grouping
        self.assertNotIn("\\", profile.catcode_overrides)
        self.assertNotIn("{", profile.catcode_overrides)
        self.assertNotIn("}", profile.catcode_overrides)
        # $ & # ^ _ ~ % are made CatCode.OTHER
        context = self.resolver.new_context()
        context.apply_profile(profile)
        self.assertEqual(context.catcodes["%"], 12)
        self.assertEqual(context.catcodes["$"], 12)

    def test_listings_option_resolution_and_validation(self):
        self.resolver.load_package("listings")

        # Valid escapeinside option
        profile = self.resolver.resolve_environment(
            "lstlisting",
            options={"language": "Python", "escapeinside": "{(*@}{@*)}"}
        )
        self.assertIsInstance(profile, EffectiveReadingProfile)
        self.assertEqual(profile.active_options["escapeinside"], ("(*@", "@*)"))

        # Valid escapechar option
        profile2 = self.resolver.resolve_environment(
            "lstlisting",
            options={"escapechar": "|"}
        )
        self.assertIsInstance(profile2, EffectiveReadingProfile)
        self.assertEqual(profile2.active_options["escapechar"], "|")

        # Malformed escapechar (multiple characters)
        res_err = self.resolver.resolve_environment(
            "lstlisting",
            options={"escapechar": "INVALID"}
        )
        self.assertIsInstance(res_err, UnresolvedBindingResult)
        self.assertEqual(res_err.reason, UnresolvedReason.UNSUPPORTED_READING_OPTION)

    def test_fancyvrb_option_resolution(self):
        self.resolver.load_package("fancyvrb")
        profile = self.resolver.resolve_environment(
            "Verbatim",
            options={"commandchars": r"\\\{\}"}
        )
        self.assertIsInstance(profile, EffectiveReadingProfile)
        self.assertEqual(profile.active_options["commandchars"], ("\\", "{", "}"))

    def test_unknown_environment_reports_unresolved(self):
        res = self.resolver.resolve_environment("non_existent_env")
        self.assertIsInstance(res, UnresolvedBindingResult)
        self.assertEqual(res.reason, UnresolvedReason.UNKNOWN_CONSTRUCT)


class ReaderContextAndExplSyntaxTests(unittest.TestCase):
    def setUp(self):
        self.resolver = BindingResolver()
        self.context = self.resolver.new_context()

    def test_expl3_leaves_at_unchanged_after_makeatletter(self):
        # 1. Baseline: @ is CatCode.OTHER (12)
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

        # 2. \makeatletter -> @ becomes LETTER (11)
        makeatletter = self.resolver.resolve_command(r"\makeatletter")
        self.context.apply_profile(makeatletter)
        self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)

        # 3. \ExplSyntaxOn -> @ MUST REMAIN CatCode.LETTER (11)
        expl_on = self.resolver.resolve_command(r"\ExplSyntaxOn")
        self.context.apply_profile(expl_on)
        self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)

        # Expl3 assigns _ and : as LETTER (11)
        self.assertEqual(self.context.catcodes["_"], CatCode.LETTER)
        self.assertEqual(self.context.catcodes[":"], CatCode.LETTER)
        # Expl3 assigns spaces and tabs as IGNORED (9)
        self.assertEqual(self.context.catcodes[" "], CatCode.IGNORED)
        self.assertEqual(self.context.catcodes["\t"], CatCode.IGNORED)
        # Expl3 assigns ~ as SPACE (10)
        self.assertEqual(self.context.catcodes["~"], CatCode.SPACE)
        # Expl3 assigns " and | as OTHER (12), ^ as SUPERSCRIPT (7)
        self.assertEqual(self.context.catcodes['"'], CatCode.OTHER)
        self.assertEqual(self.context.catcodes["|"], CatCode.OTHER)
        self.assertEqual(self.context.catcodes["^"], CatCode.SUPERSCRIPT)
        # Expl3 assigns endlinechar = 32
        self.assertEqual(self.context.endlinechar, 32)

        # 4. \ExplSyntaxOff -> restores baseline parameters
        expl_off = self.resolver.resolve_command(r"\ExplSyntaxOff")
        self.context.apply_profile(expl_off)
        # @ must STILL be CatCode.LETTER (11) because ExplSyntax did not mutate it!
        self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)
        # _ restored to SUBSCRIPT (8)
        self.assertEqual(self.context.catcodes["_"], CatCode.SUBSCRIPT)
        # : restored to OTHER (12)
        self.assertEqual(self.context.catcodes[":"], CatCode.OTHER)
        # space restored to SPACE (10)
        self.assertEqual(self.context.catcodes[" "], CatCode.SPACE)
        # endlinechar restored to 13
        self.assertEqual(self.context.endlinechar, 13)

        # 5. \makeatother -> @ becomes OTHER (12)
        makeatother = self.resolver.resolve_command(r"\makeatother")
        self.context.apply_profile(makeatother)
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_expl3_repeated_calls_are_idempotent(self):
        expl_on = self.resolver.resolve_command(r"\ExplSyntaxOn")
        expl_off = self.resolver.resolve_command(r"\ExplSyntaxOff")

        # First entry
        self.context.apply_profile(expl_on)
        self.assertTrue(self.context.expl3_active)
        self.assertEqual(self.context.catcodes["_"], CatCode.LETTER)

        # Second entry (repeated call) - must not overwrite saved baseline!
        self.context.apply_profile(expl_on)
        self.assertTrue(self.context.expl3_active)

        # Single exit should restore baseline
        self.context.apply_profile(expl_off)
        self.assertFalse(self.context.expl3_active)
        self.assertEqual(self.context.catcodes["_"], CatCode.SUBSCRIPT)
        self.assertEqual(self.context.catcodes[":"], CatCode.OTHER)

        # Repeated exit is a no-op
        self.context.apply_profile(expl_off)
        self.assertFalse(self.context.expl3_active)

    def test_execution_modes_suppress_active_mutators(self):
        makeatletter = self.resolver.resolve_command(r"\makeatletter")

        # 1. Active execution mode: mutator applies
        self.context.mode = ExecutionMode.ACTIVE_EXECUTION
        applied = self.context.apply_profile(makeatletter)
        self.assertTrue(applied)
        self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)

        # Reset @ to OTHER
        self.context.catcodes["@"] = CatCode.OTHER

        # 2. Inside stored definition (\def\foo{\makeatletter}): mutator does NOT apply
        with self.context.stored_definition():
            applied = self.context.apply_profile(makeatletter)
            self.assertFalse(applied)
            self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

        # 3. Inside argument scanning: mutator does NOT apply
        with self.context.argument_scanning():
            applied = self.context.apply_profile(makeatletter)
            self.assertFalse(applied)
            self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

        # 4. Inside skipped conditional branch: mutator does NOT apply
        with self.context.skipped_branch():
            applied = self.context.apply_profile(makeatletter)
            self.assertFalse(applied)
            self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

        # Still OTHER
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_lexical_scoping_pushes_and_pops_catcodes(self):
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

        # Push scope (\begingroup)
        self.context.push_scope()
        makeatletter = self.resolver.resolve_command(r"\makeatletter")
        self.context.apply_profile(makeatletter)
        self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)

        # Pop scope (\endgroup)
        self.context.pop_scope()
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)


class LexicalSourceTokenizationTests(unittest.TestCase):
    """Exercises real LaTeX source strings against the reader with binding state."""

    def setUp(self):
        self.resolver = BindingResolver()
        self.context = self.resolver.new_context()

    def test_expl3_source_tokenization_ignores_whitespace_and_newlines(self):
        """Under ExplSyntax, spaces and newlines are ignored; _ and : form control words."""
        expl_on = self.resolver.resolve_command(r"\ExplSyntaxOn")
        self.context.apply_profile(expl_on)

        # LaTeX source with multi-line expl3 code
        source = (
            "\\cs_new_protected:Npn \\foo_bar:nn #1#2 {\n"
            "  \\int_set:Nn \\l_tmpa_int { #1 + #2 }\n"
            "}"
        )
        reader = TexReader(
            source,
            catcodes=self.context.catcodes,
            endline_char=self.context.endlinechar,
        )

        tokens = list(reader)
        cs_values = [t.value for t in tokens if t.kind == TokenKind.CONTROL_SEQUENCE]

        # In expl3, \cs_new_protected:Npn is a single control sequence because _ and : are letters!
        self.assertIn("cs_new_protected:Npn", cs_values)
        self.assertIn("foo_bar:nn", cs_values)
        self.assertIn("int_set:Nn", cs_values)
        self.assertIn("l_tmpa_int", cs_values)

        # Crucially: NO space tokens should be produced from indentation or newlines!
        space_tokens = [t for t in tokens if t.catcode == CatCode.SPACE]
        self.assertEqual(len(space_tokens), 0)

    def test_comment_package_terminator_boundary_matching(self):
        """Validates that comment.sty terminator rejects suffixes and indentation."""
        self.resolver.load_package("comment")
        profile = self.resolver.resolve_environment("comment")
        term = profile.terminator
        pattern = re.compile(term.regex_pattern)

        # Column-zero exact match: PASSES
        self.assertTrue(pattern.match(r"\end{comment}"))

        # Indented match: FAILS (requires column 0)
        self.assertFalse(pattern.match(r"  \end{comment}"))

        # Trailing % comment: FAILS (comment.sty compares whole physical line)
        self.assertFalse(pattern.match(r"\end{comment}% trailing comment"))

        # Trailing text: FAILS
        self.assertFalse(pattern.match(r"\end{comment}NOT_TERMINATOR"))

    def test_verbatim_package_terminator_boundary_matching(self):
        """Validates that verbatim.sty permits horizontal space but rejects newlines."""
        self.resolver.load_package("verbatim")
        profile = self.resolver.resolve_environment("verbatim")
        term = profile.terminator
        pattern = re.compile(term.regex_pattern)

        # Exact match
        self.assertTrue(pattern.search(r"\end{verbatim}"))

        # Intervening horizontal spaces
        self.assertTrue(pattern.search(r"\end   {verbatim}"))
        self.assertTrue(pattern.search(r"\end	{verbatim}"))

        # Intervening newline: MUST FAIL
        self.assertFalse(pattern.search("\\end\n{verbatim}"))

    def test_reader_context_initialized_from_mouth_baseline_profile(self):
        ctx = self.resolver.new_context("latex_ascii")
        self.assertEqual(ctx.endlinechar, 13)
        self.assertEqual(ctx.catcodes["\\"], CatCode.ESCAPE)
        self.assertEqual(ctx.catcodes["{"], CatCode.BEGIN_GROUP)
        self.assertEqual(ctx.catcodes["}"], CatCode.END_GROUP)
        self.assertEqual(ctx.catcodes["@"], CatCode.OTHER)
        self.assertEqual(ctx.catcodes["a"], CatCode.LETTER)
        self.assertEqual(ctx.catcodes["Z"], CatCode.LETTER)


if __name__ == "__main__":
    unittest.main()
