"""Policy choices must affect emitted source without changing mouth tokens."""
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from src.prepare.emission import MouthEmitter
from src.prepare.pipeline import preprocess_paper
from src.prepare.policy import load_policy
from src.reading.tex_reader import CatCode, EventKind
from tests.reader_support import new_reader, new_catcodes


PROJECT = Path(__file__).resolve().parents[1]


def configured(**options):
    policy = load_policy("prepare")
    return replace(policy, lexical_events=replace(policy.lexical_events, **options))


def tokens(source, codes=None):
    return [(t.kind, t.value, t.catcode) for t in new_reader(
        source, catcodes=codes.copy() if codes is not None else new_catcodes())]


def emit(source, policy, codes=None):
    emitter = MouthEmitter(policy)
    output, metadata = [], []
    reader = new_reader(source, catcodes=codes.copy() if codes is not None else new_catcodes())
    while (event := reader.next_event()) is not None:
        result = emitter.emit(event, source)
        output.extend((result.text, result.suffix))
        if result.metadata:
            metadata.append(result.metadata)
    return "".join(output), metadata


class MouthEmissionPolicyTests(unittest.TestCase):
    def test_comment_policy_combinations_preserve_token_stream(self):
        cases = [
            "a% inline\nb", "a % inline\nb", "a\t% inline\nb",
            "% whole\na", "  % whole\n\nA", "\\foo% inline\nbar",
            "\\foo % inline\nbar", "a% final", "% final", "",
            "a\n% whole\n\nb", "a^^25 encoded\nb", "\\% visible\n",
            "% !TeX program = xelatex\nA", "A\n\n\nB   \n",
        ]
        for whole in ("eliminate", "preserve"):
            for inline in ("strip_payload", "preserve"):
                for directive in ("extract_metadata", "preserve", "eliminate"):
                    policy = configured(comment_line=whole, comment_inline=inline,
                                        magic_directive=directive)
                    for source in cases:
                        for newline in ("\n", "\r", "\r\n"):
                            source_variant = source.replace("\n", newline)
                            with self.subTest(whole=whole, inline=inline, directive=directive, source=source_variant):
                                output, _ = emit(source_variant, policy)
                                self.assertEqual(tokens(source_variant), tokens(output))

    def test_comment_line_and_inline_choices_are_independent(self):
        source = "% whole\nX% inline\nY"
        output, _ = emit(source, configured(comment_line="preserve"))
        self.assertIn("% whole\n", output)
        self.assertNotIn("inline", output)
        output, _ = emit(source, configured(comment_inline="preserve"))
        self.assertNotIn("whole", output)
        self.assertIn("X% inline\nY", output)

    def test_directives_override_comment_policy_and_never_execute(self):
        source = "% !TeX program = arbitrary command\n% !tex Unknown Field = opaque value\nA"
        output, metadata = emit(source, configured(comment_line="preserve"))
        self.assertNotIn("!TeX", output)
        self.assertEqual(metadata, [
            {"kind": "tex_directive", "key": "program", "value": "arbitrary command"},
            {"kind": "tex_directive", "key": "unknown field", "value": "opaque value"}])
        for action in ("preserve", "eliminate"):
            output, metadata = emit(source, configured(magic_directive=action))
            self.assertEqual(metadata, [])
            self.assertEqual("opaque value" in output, action == "preserve")
        malformed = "% !TeX no assignment\n% !TeX = no key\nX% !TeX key = inline\nY"
        output, metadata = emit(malformed, configured(comment_line="preserve", comment_inline="preserve"))
        self.assertEqual(metadata, [])
        self.assertIn("no assignment", output)
        self.assertIn("inline", output)

    def test_comment_categories_and_transformed_introducers_come_from_reader(self):
        for marker in ("%", "^^25", "!"):
            codes = new_catcodes()
            codes["!"] = CatCode.COMMENT
            source = marker + " !TeX\tprogram = xelatex\nA"
            reader = new_reader(source, catcodes=codes)
            event = reader.next_event()
            self.assertEqual(event.kind, EventKind.COMMENT)
            self.assertEqual(reader.source_slice(event.comment_marker), marker)
            output, metadata = emit(source, configured(), codes)
            self.assertEqual(metadata[0]["key"], "program")
            self.assertEqual(tokens(source, codes), tokens(output, codes))
        codes = new_catcodes()
        codes["%"] = CatCode.OTHER
        output, metadata = emit("% !TeX program = xelatex\n", configured(), codes)
        self.assertIn("!TeX", output)
        self.assertEqual(metadata, [])

    def test_classification_uses_state_not_whitespace_looking_characters(self):
        codes = new_catcodes()
        codes["\t"] = CatCode.OTHER
        output, _ = emit("\t% inline\nX", configured(comment_line="preserve"), codes)
        self.assertNotIn("inline", output)
        self.assertEqual(tokens("\t% inline\nX", codes), tokens(output, codes))

    def test_every_paragraph_token_survives_even_when_par_is_redefined(self):
        source = "\\def\\par{OBSERVABLE}\nA\n\n\n\nB\n"
        output, _ = emit(source, configured())
        self.assertEqual(tokens(source), tokens(output))
        self.assertEqual(output.count("\\par"), 4)  # definition plus three tokens

    def test_only_reader_discarded_spaces_are_removed(self):
        source = "A   \t B   \n   C\n"
        output, _ = emit(source, configured())
        self.assertEqual(tokens(source), tokens(output))
        self.assertEqual(output, "A B C ")


class PreparationEmissionPolicyTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "prepared"
        self.policy = self.root / "custom.yaml"

    def write_policy(self, settings=""):
        self.policy.write_text("identity: {name: custom}\n" + settings, encoding="utf-8")

    def prepare(self, source, settings="", **kwargs):
        (self.source / "main.tex").write_text(source, encoding="utf-8", newline="")
        self.write_policy(settings)
        return preprocess_paper(str(self.source), str(self.output), root_tex="main.tex",
                                policy=self.policy, **kwargs)

    def test_repeated_inputs_kept_eof_comments_metadata_and_locations(self):
        (self.source / "part.tex").write_text("% !TeX program = xelatex\nX% terminal", encoding="utf-8")
        original = "A\\input{part}B\\input{part}C\n"
        text, manifest, _, ledger = self.prepare(original,
            "lexical_events: {comment_inline: preserve}\n")
        self.assertIn("X% terminal\nB", text)
        self.assertIn("X% terminal\nC", text)
        self.assertEqual(text.count("terminal"), 2)
        self.assertEqual(len(manifest.source_metadata), 2)
        units = {u["id"]: u for u in manifest.units}
        occurrences = []
        for metadata in manifest.source_metadata:
            unit = units[metadata["unit_id"]]
            self.assertEqual(metadata["location_status"], "omitted")
            self.assertEqual(metadata["locations"], [])
            occurrences.append(unit["origin"]["occurrence"])
        self.assertEqual(len(set(occurrences)), 2)
        self.assertTrue(all(not r["unaccounted"] for r in ledger.source_coverage))
        endings = [s for s in ledger.segments if s["operation"] == "SYNTHETIC_COMMENT_END"]
        self.assertEqual(len(endings), 2)
        self.assertTrue(all(s["mapping"] == "insert" and s["source"][0] == s["source"][1] for s in endings))
        self.assertEqual((self.source / "main.tex").read_text(), original)

    def test_protected_bodies_and_retained_code_are_not_normalized(self):
        definition = "\\def\\sample{A% !TeX program = hidden\n   B   }"
        literal = "\\verb|x % untouched   |"
        local = "% !TeX program = local\n\\def\\local{X% kept\nY}\n"
        (self.source / "local.sty").write_text(local, encoding="utf-8")
        source = "\\usepackage{local}\n" + definition + "\n" + literal + "\nX% removed\nY"
        text, manifest, out, ledger = self.prepare(source)
        self.assertIn(definition, text)
        self.assertIn(literal, text)
        self.assertNotIn("removed", text)
        self.assertEqual(manifest.source_metadata, [])
        self.assertEqual((out / "local.sty").read_text(), local)
        self.assertTrue(all(not r["unaccounted"] for r in ledger.source_coverage))

    def test_stripped_terminal_comment_keeps_only_suppression_and_accounts_for_payload(self):
        source = "A% terminal payload"
        text, _, _, ledger = self.prepare(source)
        self.assertEqual(text, "A%\n")
        self.assertEqual(tokens(source), tokens(text))
        self.assertTrue(any(t.src_start == 2 and t.src_end == len(source) for t in ledger.tombstones))
        self.assertTrue(any(s["source"][0] <= 1 and s["source"][1] == 2 and s["mapping"] == "copy"
                            for s in ledger.segments))
        self.assertTrue(all(not r["unaccounted"] for r in ledger.source_coverage))

    def test_transformed_root_hint_shares_the_comment_metadata_parser(self):
        nested = self.source / "nested"
        nested.mkdir()
        (self.source / "hint.tex").write_text("^^25 !TeX root = nested/main.tex\n", encoding="utf-8")
        (nested / "main.tex").write_text("\\documentclass{article}\nA", encoding="utf-8")
        (self.source / "other.tex").write_text("\\documentclass{article}\nB", encoding="utf-8")
        _, manifest, _, _ = preprocess_paper(str(self.source), str(self.output))
        self.assertEqual(manifest.root_file, "nested/main.tex")

    def test_provenance_yaml_and_explicit_api_override_are_honored(self):
        disabled = "provenance: {emit_ledger: false}\n"
        _, manifest, out, ledger = self.prepare("ABC\n", disabled)
        self.assertIsNone(ledger)
        self.assertFalse((out / "master.provenance.json").exists())
        self.assertTrue(manifest.prepared_artifacts)
        _, _, out, ledger = self.prepare("ABC\n", disabled, emit_provenance=True)
        self.assertIsNotNone(ledger)
        self.assertTrue((out / "master.provenance.json").exists())
        _, _, out, ledger = self.prepare("ABC\n", emit_provenance=False)
        self.assertIsNone(ledger)
        self.assertFalse((out / "master.provenance.json").exists())

    def test_rle_choice_changes_representation_not_content_or_locations(self):
        text, manifest, _, compact = self.prepare("ABCDE\n")
        other, other_manifest, out, expanded = self.prepare("ABCDE\n",
            "provenance: {rle_compression: false}\n")
        self.assertEqual(text, other)
        self.assertEqual(manifest.units, other_manifest.units)
        self.assertEqual(compact.source_coverage, expanded.source_coverage)
        self.assertGreater(len(expanded.segments), len(compact.segments))
        self.assertEqual(json.loads((out / "master.provenance.json").read_text())["segments"], expanded.segments)
        for ledger in (compact, expanded):
            for s in ledger.segments:
                if s["mapping"] == "copy":
                    self.assertEqual(s["source"][1] - s["source"][0], s["generated"][1] - s["generated"][0])

    def test_unsupported_settings_fail_before_source_reads_and_preserve_previous_payload(self):
        self.prepare("LAST GOOD\n")
        before = (self.output / "master.tex").read_bytes()
        cases = [
            ("lexical_events: {comment_line: route_to_sidecar}", "comment_line"),
            ("lexical_events: {line_continuation: eliminate}", "line_continuation"),
            ("structural_normalization: {paragraph_breaks: coalesce}", "paragraph_breaks"),
            ("structural_normalization: {trailing_whitespace: preserve}", "trailing_whitespace"),
        ]
        for settings, field in cases:
            with self.subTest(field=field):
                self.write_policy(settings)
                with patch("src.prepare.session.SourceStore") as store:
                    with self.assertRaisesRegex(ValueError, field) as caught:
                        preprocess_paper(str(self.source), str(self.output), policy=self.policy)
                    store.assert_not_called()
                self.assertIn(str(self.policy), str(caught.exception))
                self.assertEqual((self.output / "master.tex").read_bytes(), before)
                self.assertEqual(list(self.root.glob(".pytexml-publish-*")), [])


if __name__ == "__main__":
    unittest.main()
