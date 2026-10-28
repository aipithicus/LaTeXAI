"""TeX raw meaning identity, explicit undefined state, and preparation reuse."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.prepare.session import PreparationSession
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import (ConditionalRegion, ReadingBoundary, SourceCommand,
                                  StoredDefinition, UndefinedMeaning)
from src.reading.coverage import ReadingCoverage
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import CatCode, TexReader


class MeaningComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def read(self, source, *, complete=True, preparation=True, packages=()):
        knowledge = BindingResolver(self.catalog, engine_profile="pdftex")
        for package in packages:
            knowledge.load_package(package)
        context = knowledge.new_context()
        reader = TexReader(source, source_id="comparison.tex", catcodes=context.catcodes,
                           endline_char=context.endlinechar)
        host = StructuralDispatcher(reader, context, knowledge, source_commands=True, preparation=preparation)
        self.items = list(host)
        self.assertEqual(isinstance(self.items[-1], ReadingBoundary), not complete, self.items[-1:])
        if complete:
            ReadingCoverage(reader.basis, self.items)
        self.host = host
        return context

    def truths(self):
        return [d["truth"] for d in self.host.decisions if d["predicate"] == "meaning_equal"]

    def test_known_meanings_select_without_expanding_operands(self):
        context = self.read(r"\def\a{\missing}\def\b{\missing}\ifx\a\b\def\chosen{yes}\else\unknown\fi")
        self.assertEqual(self.truths(), [True])
        self.assertEqual(context.lookup_definition("chosen").body_tokens[0].value, "y")
        self.assertIsNone(context.lookup_meaning("missing"))

    def test_macro_body_control_sequences_compare_identity_not_current_meaning(self):
        self.read(r"\let\c\relax\let\d\relax\def\a{\c}\def\b{\d}\ifx\a\b BAD\else GOOD\fi")
        self.assertEqual(self.truths(), [False])

    def test_character_alias_and_chardef_are_different_meaning_kinds(self):
        self.read(r"\let\a=A\chardef\b=65 \ifx\a A Y\fi\ifx\b A BAD\fi\chardef\c=65 \ifx\b\c Y\fi")
        self.assertEqual(self.truths(), [True, False, True])

    def test_parameter_identity_does_not_depend_on_cell_value(self):
        self.read(r"\widowpenalty=17 \clubpenalty=17 \let\saved\widowpenalty"
                  r"\ifx\widowpenalty\clubpenalty BAD\fi"
                  r"\widowpenalty=23 \ifx\saved\widowpenalty YES\fi"
                  r"\def\widowpenalty{shadow}\ifx\saved\widowpenalty BAD\fi")
        self.assertEqual(self.truths(), [False, True, False])

    def test_def_variants_share_handler_but_have_distinct_tex_meanings(self):
        self.read(r"\let\saved\gdef\ifx\saved\gdef YES\fi"
                  r"\ifx\def\gdef BAD\fi\ifx\def\edef BAD\fi\ifx\gdef\xdef BAD\fi")
        self.assertEqual(self.truths(), [True, False, False, False])

    def test_raw_spaces_and_group_operands_do_not_change_scopes(self):
        self.read(r"\ifx a YES\else NO\fi\ifx{{YES\else NO\fi")
        self.assertEqual(self.truths(), [False, True])
        self.assertEqual(self.host.context.scope_depth, 0)

    def test_active_character_meaning_and_control_symbol_identity(self):
        self.read(r"\catcode126=13\def~{X}\def\a{X}\ifx~\a YES\fi"
                  r"\def\b{~}\def\c{\~}\ifx\b\c BAD\fi")
        self.assertEqual(self.truths(), [True, False])

    def test_active_character_does_not_borrow_control_symbol_profile(self):
        from src.engine.expansion import ExpansionCursor
        from src.reading.contracts import ReadingIssue, UncertainMeaning

        knowledge = BindingResolver(self.catalog)
        resolve = knowledge.resolve_command
        # A provider for the control symbol exists; the active character is
        # deliberately absent. Exercise lookup, not a spelling absent everywhere.
        with patch.object(knowledge, "resolve_command",
                          side_effect=lambda name: resolve("widowpenalty") if name == "~" else resolve(name)):
            for source, action in ((r"~", "expansion"),
                                   (r"\widowpenalty=17 \chardef\a=+\noexpand~", "integer"),
                                   (r"\let\a~", "let")):
                with self.subTest(action=action):
                    context = knowledge.new_context()
                    reader = TexReader(source, catcodes=context.catcodes, endline_char=context.endlinechar)
                    host = StructuralDispatcher(reader, context, knowledge)
                    if action == "expansion":
                        cursor = ExpansionCursor(reader, context, knowledge, host.operations)
                        with self.assertRaises(ReadingIssue) as caught:
                            cursor.next_expanded()
                        self.assertEqual(caught.exception.reason, "expansion_required")
                    elif action == "integer":
                        items = list(host)
                        self.assertEqual(items[-1].reason, "computed_assignment")
                        self.assertIsNone(context.lookup_meaning("a"))
                    else:
                        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in host))
                        self.assertIsInstance(context.lookup_meaning("a"), UncertainMeaning)

    def test_definition_categories_survive_later_catcode_changes(self):
        self.read(r"\def\a{!}\catcode33=11\def\b{!}\ifx\a\b BAD\else GOOD\fi")
        self.assertEqual(self.truths(), [False])

    def test_parameter_text_and_compiled_replacement_markers(self):
        self.read(r"\def\a#1,#2;{#2##:#1}\def\b#1,#2;{#2##:#1}\def\c#1;#2;{#2##:#1}"
                  r"\ifx\a\b YES\fi\ifx\a\c BAD\fi"
                  r"\def\a#1#{#1}\def\b#1#{#1}\ifx\a\b YES\fi")
        self.assertEqual(self.truths(), [True, False, True])

    def test_newcommand_long_flag_and_primitive_definition_equivalence(self):
        self.read(r"\newcommand{\a}[1]{#1}\newcommand*{\b}[1]{#1}\def\c#1{#1}"
                  r"\ifx\a\b BAD\fi\ifx\b\c YES\fi")
        self.assertEqual(self.truths(), [False, True])

    def test_expanded_and_raw_replacements_compare_as_compiled_tokens(self):
        self.read(r"\def\a{X}\edef\b{\a}\def\c{X}\def\d{\a}"
                  r"\ifx\b\c YES\fi\ifx\b\d BAD\fi"
                  r"\def\e{}\ifx\e\CurrentOption YES\fi")
        self.assertEqual(self.truths(), [True, False, True])

    def test_alias_copies_redefinition_and_scope_restoration(self):
        self.read(r"\def\a{X}\let\b\a{\def\a{Y}\ifx\a\b BAD\fi}\ifx\a\b YES\fi"
                  r"{\gdef\a{Z}}\ifx\a\b BAD\fi")
        self.assertEqual(self.truths(), [False, True, False])

    def test_conditional_tokens_are_operands_not_nested_markers(self):
        self.read(r"\ifx\fi\else BAD\else GOOD\fi")
        self.assertEqual(self.truths(), [False])

    def test_alias_of_ifx_survives_spelling_redefinition(self):
        self.read(r"\let\compare\ifx\def\ifx{shadow}\compare aa YES\fi")
        self.assertEqual(self.truths(), [True])

    def test_known_boolean_conditional_matches_primitive(self):
        self.read(r"\newif\ifflag\ifx\ifflag\iffalse YES\fi\flagtrue\ifx\ifflag\iftrue YES\fi")
        self.assertEqual(self.truths(), [True, True])

    def test_unavailable_means_deferred_even_when_both_names_are_missing(self):
        self.read(r"\ifx\unknown\other A\else B\fi")
        self.assertEqual(self.truths(), [])
        self.assertEqual(sum(isinstance(i, ConditionalRegion) for i in self.items), 1)
        self.assertIsNone(self.host.context.lookup_meaning("unknown"))

    def test_identical_unknown_token_is_equal_without_guessing_its_meaning(self):
        self.read(r"\ifx\unknown\unknown Y\fi")
        self.assertEqual(self.truths(), [True])
        self.assertIsNone(self.host.context.lookup_meaning("unknown"))

    def test_optional_wrappers_only_compare_when_known_copied(self):
        self.read(r"\newcommand{\a}[1][x]{#1}\let\b\a\newcommand{\c}[1][x]{#1}"
                  r"\ifx\a\b YES\fi\ifx\a\c A\else B\fi")
        self.assertEqual(self.truths(), [True])
        self.assertEqual(sum(isinstance(i, ConditionalRegion) for i in self.items), 1)

    def test_uncompiled_environment_pair_is_not_one_macro_meaning(self):
        self.read(r"\NewEnviron{foo}{A}\ifx\foo\endfoo A\else B\fi", packages=("environ",))
        self.assertIsNotNone(self.host.context.lookup_definition("foo"))
        self.assertEqual(self.truths(), [])

    def test_undefined_state_can_be_copied_shadowed_and_restored(self):
        context = self.read(r"\let\a\undefined\ifx\a\undefined YES\fi"
                            r"{\def\undefined{X}\ifx\a\undefined BAD\fi}"
                            r"\ifx\a\undefined YES\fi\ifx\a\relax BAD\fi")
        self.assertEqual(self.truths(), [True, False, True, False])
        self.assertIsInstance(context.lookup_meaning("a"), UndefinedMeaning)
        self.assertIsNotNone(context.lookup_meaning("undefined").format_origin)

    def test_undefined_overrides_a_known_provider_and_can_be_defined_again(self):
        context = self.read(r"\let\iftrue\undefined\ifx\iftrue\undefined YES\fi"
                            r"\newcommand{\iftrue}{X}\def\b{X}\ifx\iftrue\b NO\else YES\fi")
        self.assertEqual(self.truths(), [True, False])  # newcommand is long.
        declaration = next(i for i in self.items if isinstance(i, StoredDefinition) and i.target.value == "iftrue")
        self.assertEqual(declaration.target_check, "known_absent")
        self.assertIsNotNone(context.lookup_definition("iftrue"))

    def test_renew_of_known_undefined_is_rejected(self):
        self.read(r"\let\a\undefined\renewcommand{\a}{X}", complete=False)
        self.assertEqual(self.items[-1].reason, "definition_conflict")

    def test_environment_preconditions_honor_known_undefined(self):
        self.read(r"\let\foo\undefined\let\endfoo\undefined\NewEnviron{foo}{A}", packages=("environ",))
        self.assertEqual(self.host.context.lookup_definition("foo").target_check, "known_absent")
        self.read(r"\let\foo\undefined\RenewEnviron{foo}{A}", complete=False, packages=("environ",))
        self.assertEqual(self.items[-1].reason, "definition_conflict")

    def test_executing_or_expanding_known_undefined_does_not_fall_back(self):
        for source in (r"\let\relax\undefined\relax", r"\edef\a{\undefined}"):
            with self.subTest(source=source):
                self.read(source, complete=False)
                self.assertEqual(self.items[-1].reason, "undefined_control_sequence")

    def test_unexecuted_source_invalidates_sentinel_and_copies_in_saved_scopes(self):
        self.read(r"\let\a\undefined{\def\undefined{X}\unknown}"
                  r"\ifx\a\undefined A\else B\fi")
        self.assertEqual(self.truths(), [])
        self.assertIsNotNone(self.host.context.lookup_meaning("a").uncertain)
        self.assertIsNotNone(self.host.context.lookup_meaning("undefined").uncertain)

    def test_unexecuted_definition_prevents_comparison_with_old_definition(self):
        self.read(r"\def\a{X}\def\b{X}\ifx\missing\other\def\a{Y}\fi"
                  r"\ifx\a\b A\else B\fi")
        self.assertEqual(self.truths(), [])

    def test_uncertain_undefined_state_does_not_establish_nonconditional_meaning(self):
        self.read(r"\unknown\iffalse\undefined\fi", complete=False)
        self.assertEqual(self.items[-1].reason, "uncertain_meaning")

    def test_failed_probe_restores_raw_cursor_and_keeps_full_envelope(self):
        source = r"\ifx\fi\unknown A\else B\fi AFTER"
        self.read(source)
        region = next(i for i in self.items if isinstance(i, ConditionalRegion))
        self.assertEqual(source[region.span.start:region.span.end], source.removesuffix(" AFTER"))
        self.assertEqual(self.truths(), [])

    def test_skipped_ifx_does_not_read_or_expand_its_operands(self):
        self.read(r"\iffalse\ifx\unknown\other\fi\fi AFTER")
        self.assertEqual(self.truths(), [])

    def test_strict_execution_and_frozen_option_replay_share_the_predicate(self):
        self.read(r"\ifx aa\def\selected{Y}\fi", preparation=False)
        self.assertEqual(self.truths(), [True])
        from reader_support import requested_options
        from src.reading.options import OptionScope
        knowledge = BindingResolver(self.catalog, engine_profile="pdftex")
        context = knowledge.new_context()
        source = r"\DeclareOption{x}{\ifx\pdfoutput\undefined\unknown\else\def\selected{Y}\fi}\ProcessOptions"
        reader = TexReader(source, catcodes=context.catcodes, endline_char=context.endlinechar)
        host = StructuralDispatcher(reader, context, knowledge, options=OptionScope("local", requested_options(context, ("x",))))
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in host))
        self.assertIsNotNone(context.lookup_definition("selected"))

    def test_independent_tex_witness(self):
        fixture = PROJECT / "tests/fixtures/engine"
        # Diagnostic expansion is a separate, unsupported operation. The oracle
        # reports completed assignments only after all comparisons have run.
        source = (fixture / "meaning-comparison.tex").read_text().split(r"\typeout")[0]
        expected = json.loads((fixture / "meaning-comparison.expected.json").read_text())
        self.read(source)
        self.assertEqual(expected.pop("sentinel_plain"), "undefined")
        self.assertEqual(expected.pop("sentinel_at"), "undefined")
        observed = {key: "".join(t.value for t in self.host.context.lookup_definition(
            "PyWitness" + key.replace("_", "")).replacement_tokens) for key in expected}
        self.assertEqual(len(self.truths()), len(expected))
        self.assertEqual(observed, expected)


class MeaningComparisonPreparationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, source):
        (self.root / name).write_text(source, encoding="utf-8", newline="\n")

    def test_actual_gauntlet_class_engine_probe(self):
        source = (PROJECT / "tests/fixtures/specimens/gauntlet-master/gmvenue.cls").read_text()
        source = source[:source.index(r"\ifdefined")]
        self.put("gmvenue.cls", source)
        self.put("main.tex", r"\pdfoutput=1 \documentclass[11pt]{gmvenue}")
        session = PreparationSession(self.root, engine_profile="pdftex").run()
        self.assertEqual(session.manifest.unresolved, [])
        self.assertEqual([d["truth"] for d in session.dispatcher.decisions if d["predicate"] == "meaning_equal"],
                         [False, False])
        self.assertEqual("".join(t.value for t in session.context.lookup_definition("gm@engine").replacement_tokens),
                         "pdfoutput")
        self.assertIsNone(session.context.lookup_meaning("active").uncertain)

    def test_selected_input_and_operand_separator_preserve_payload(self):
        self.put("yes.tex", "YES")
        self.put("main.tex", r"\documentclass{article}\let\alias\relax"
                 r"\ifx\alias\relax\input{yes}\else\input{missing}\fi")
        text, manifest, _, ledger = preprocess_paper(str(self.root))
        self.assertFalse(manifest.unresolved)
        self.assertIn(r"\ifx\alias\relax YES", text)
        self.assertNotIn("missing", text)
        self.assertEqual([d["target"] for d in manifest.dependencies], ["yes.tex"])
        self.assertFalse(any(c["unaccounted"] for c in ledger.source_coverage))


if __name__ == "__main__":
    unittest.main()
