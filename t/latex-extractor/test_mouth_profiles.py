"""Regex/profile behavior tested against explicit source and category expectations."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python/latex-extractor"))

from binding_resolver import BindingResolver
from character_rules import CharacterRule, ProfileError, compile_layer
from mouth_profiles import MouthProfiles
from tex_reader import CatCode, TexReader


def rule(name, pattern, code):
    return {"id": name, "kind": "catcode_run", "domain": "mouth_characters",
            "pattern": pattern, "catcode": code}


class RegexContractTests(unittest.TestCase):
    def test_full_span_membership_and_maximal_coverage(self):
        letters = CharacterRule("letters", r"[A-Za-z]+", 11)
        self.assertTrue(letters.fullmatch("abc"))
        self.assertFalse(letters.fullmatch("abc2"))
        self.assertFalse(letters.fullmatch(""))
        self.assertTrue(letters.fullmatch("!abc?", 1, 4))
        self.assertEqual(list(letters.spans("abc12 DEF")), [(0, 3), (6, 9)])
        self.assertEqual(list(letters.spans("abc12 DEF", 1, 8)), [(1, 3), (6, 8)])
        self.assertEqual(list(letters.spans("123")), [])
        with self.assertRaises(ValueError):
            list(letters.spans("abc", 0, 4))

    def test_unicode_and_complement_sets_are_regex_semantics(self):
        greek = CharacterRule("greek", r"[\u03B1-\u03C9]+", 11)
        self.assertTrue(greek.fullmatch("αβω"))
        self.assertFalse(greek.fullmatch("αA"))
        non_ascii = CharacterRule("non_ascii", r"[^\x00-\x7f]+", 12)
        self.assertEqual(list(non_ascii.spans("aé🙂b")), [(1, 3)])
        # These offsets belong to decoded characters, without Unicode normalization.
        self.assertEqual(list(greek.spans("α\u0301β")), [(0, 1), (2, 3)])

    def test_invalid_or_contextual_catcode_patterns_are_rejected(self):
        for pattern in (r"[A-Z", r"[z-a]+", r"[A-Z]*", r"[A-Z]", r"ab+",
                        r"^[A-Z]+$", r"[A-Z]{2}", r"(?i)[a-z]+", r"[a&&b]+"):
            with self.subTest(pattern=pattern), self.assertRaises(ProfileError):
                CharacterRule("broken", pattern, 11)

    def test_conflicts_are_diagnosed_and_explicit_assignments_override(self):
        config = {"character_classes": [rule("letters", "[a-z]+", 11),
                                         rule("a", "[a]+", 12)]}
        with self.assertRaisesRegex(ProfileError, "letters.*a"):
            compile_layer(config, "test")
        config["catcode_overrides"] = {"a": 13}
        layer = compile_layer(config, "test")
        self.assertEqual(layer.resolve("a"), 13)
        self.assertEqual(layer.resolve("b"), 11)
        unicode_layer = compile_layer({"character_classes": [
            rule("one", "[é]+", 11), rule("two", "[é]+", 12)]}, "unicode")
        with self.assertRaisesRegex(ProfileError, "U\\+00E9"):
            unicode_layer.resolve("é")

    def test_bad_assignments_never_silently_disappear_or_coerce(self):
        for lexical in ({"catcode_overrides": {"backslash": 0}},
                        {"catcode_overrides": {"%": 12.9}},
                        {"catcode_overrides": {"%": True}},
                        {"catcode_overrides": {"%": "14"}},
                        {"assignments": {"letters": "a-z"}},
                        {"reader_parameters": {"endlinechar": False}},
                        {"character_classes": [rule("bad", "[a]+", 16)]}):
            with self.subTest(lexical=lexical), self.assertRaises(ProfileError):
                compile_layer(lexical, "bad")
        wrong_domain = rule("bad", "[a]+", 11)
        wrong_domain["domain"] = "raw_bytes"
        with self.assertRaises(ProfileError):
            compile_layer({"character_classes": [wrong_domain]}, "bad")


class MouthIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolver = BindingResolver()

    def test_entire_ascii_baseline_and_unicode_default(self):
        codes = self.resolver.new_context().catcodes
        specials = {"\\": 0, "{": 1, "}": 2, "$": 3, "&": 4, "\r": 5,
                    "#": 6, "^": 7, "_": 8, "\0": 9, " ": 10, "\t": 10,
                    "~": 13, "\f": 13, "%": 14, "\x7f": 15}
        for number in range(128):
            char = chr(number)
            expected = 11 if "A" <= char <= "Z" or "a" <= char <= "z" else specials.get(char, 12)
            self.assertEqual(codes[char], expected, repr(char))
        for char in ("é", "α", "🙂", "\u00a0"):
            self.assertEqual(codes[char], CatCode.OTHER)

    def test_literal_profiles_preserve_spaces_tabs_and_specials(self):
        resolver = BindingResolver()
        resolver.load_package("fancyvrb")
        resolver.load_package("listings")
        body = "  a\t  b%\\{}$&#^_~"
        for command in ("verb", "verb*", "Verb", "lstinline"):
            with self.subTest(command=command):
                profile = resolver.resolve_command(command)
                ctx = resolver.new_context()
                ctx.apply_profile(profile)
                tokens = list(TexReader(body, catcodes=ctx.catcodes, endline_char=-1))
                self.assertEqual("".join(t.value for t in tokens), body)
                self.assertEqual(ctx.catcodes[" "], CatCode.ACTIVE)
                self.assertEqual(ctx.catcodes["\t"], CatCode.ACTIVE)
                self.assertEqual(ctx.catcodes["a"], CatCode.LETTER)
        raw = resolver.mouth.layers("raw_block")[0].rules[0]
        self.assertTrue(raw.fullmatch("\\{}$&#^_~%"))
        self.assertFalse(raw.fullmatch("a"))
        self.assertFalse(raw.fullmatch(" "))

    def test_semi_verbatim_retains_inherited_command_and_group_categories(self):
        resolver = BindingResolver()
        resolver.load_package("alltt")
        ctx = resolver.new_context()
        ctx.apply_profile(resolver.resolve_environment("alltt"))
        self.assertEqual([ctx.catcodes[c] for c in "\\{}% "], [0, 1, 2, 12, 13])

    def test_regex_layers_runtime_assignments_caches_and_scopes(self):
        ctx = self.resolver.new_context()
        self.assertEqual(ctx.catcodes["%"], 14)  # Populate cache.
        ctx.catcodes["%"] = 0
        with ctx.lexical_scope():
            ctx.apply_profile(self.resolver.resolve_environment("verbatim"))
            self.assertEqual(ctx.catcodes["%"], 12)  # New effect beats earlier assignment.
            ctx.catcodes["%"] = 14
            self.assertEqual(ctx.catcodes["%"], 14)
            clone = ctx.copy()
            clone.catcodes["%"] = 9
            self.assertEqual(ctx.catcodes["%"], 14)
        self.assertEqual(ctx.catcodes["%"], 0)
        ctx.catcodes.default = CatCode.LETTER
        self.assertEqual(ctx.catcodes["🙂"], 11)

    def test_no_io_or_regex_recompilation_after_bootstrap(self):
        with patch.object(Path, "open", side_effect=AssertionError("Unexpected I/O")), \
             patch("character_rules.re.compile", side_effect=AssertionError("Unexpected compilation")):
            ctx = self.resolver.new_context()
            profile = self.resolver.resolve_environment("verbatim")
            ctx.apply_profile(profile)
            self.assertEqual("".join(t.value for t in TexReader(
                "a  b", catcodes=ctx.catcodes, endline_char=-1)), "a  b")
            regex = profile.catcode_layers[0].rules[0]
            self.assertEqual(list(regex.spans("a%\\b")), [(1, 3)])

    def test_registry_is_separate_and_wrong_baseline_kind_is_rejected(self):
        self.assertIn("native_operations", self.resolver.operation_registries)
        self.assertNotIn("operations", self.resolver.profiles)
        with self.assertRaisesRegex(ProfileError, "baseline_catcodes"):
            self.resolver.new_context("raw_block")


class ProfileLoadingTests(unittest.TestCase):
    def setUp(self):
        root = REPO / "temp/t/latex-extractor"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def write(self, name, text):
        (self.directory / name).write_text(text, encoding="utf-8", newline="\n")

    def test_inherited_regex_effects_overlay_parent_explicit_assignments(self):
        self.write("parent.yaml", """identity: {name: parent, category: baseline_catcodes}
lexical_mode:
  default: 12
  reader_parameters: {endlinechar: -1}
  catcode_overrides: {a: 12}
""")
        self.write("child.yaml", """identity: {name: child, category: baseline_catcodes}
inherits: parent
lexical_mode:
  character_classes:
    - {id: letters, kind: catcode_run, domain: mouth_characters, pattern: '[a-z]+', catcode: 11}
""")
        baseline = MouthProfiles(self.directory).baseline("child")
        self.assertEqual(baseline.new_catcodes()["a"], 11)
        self.assertEqual(baseline.endlinechar, -1)

    def test_duplicate_yaml_keys_are_rejected(self):
        self.write("bad.yaml", "identity: {name: a, name: b, category: baseline_catcodes}\n")
        with self.assertRaisesRegex(ProfileError, "Duplicate YAML key"):
            MouthProfiles(self.directory)

    def test_duplicate_profile_names_are_rejected(self):
        for name in ("one.yaml", "two.yaml"):
            self.write(name, "identity: {name: same, category: inline_literal}\n")
        with self.assertRaisesRegex(ProfileError, "duplicate identity"):
            MouthProfiles(self.directory)

    def test_missing_and_cyclic_inheritance_are_rejected(self):
        self.write("a.yaml", "identity: {name: a, category: inline_literal}\ninherits: b\n")
        with self.assertRaisesRegex(ProfileError, "Unknown mouth profile"):
            MouthProfiles(self.directory)
        self.write("b.yaml", "identity: {name: b, category: inline_literal}\ninherits: a\n")
        with self.assertRaisesRegex(ProfileError, "Cyclic mouth inheritance"):
            MouthProfiles(self.directory)

    def test_missing_directory_does_not_fall_back(self):
        with self.assertRaisesRegex(ProfileError, "Missing mouth profile directory"):
            MouthProfiles(self.directory / "missing")

    def test_misspelled_configuration_does_not_become_an_empty_profile(self):
        self.write("bad.yaml", "identity: {name: bad, category: inline_literal}\nlexical_mod: {}\n")
        with self.assertRaisesRegex(ProfileError, "unknown profile keys.*lexical_mod"):
            MouthProfiles(self.directory)


if __name__ == "__main__":
    unittest.main()
