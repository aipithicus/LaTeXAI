"""Reading witnesses from environ v0.3's env@new and Collect@@Body.

Source: https://ctan.math.illinois.edu/macros/latex/contrib/environ/environ.dtx
No body execution, template expansion, source trimming or TeX engine is needed.
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from reader_support import reload_catalog, requested_options
from src.bindings.resolver import BindingResolver
from src.prepare.pipeline import preprocess_paper
from src.reading.character_rules import ProfileError
from src.reading.contracts import CollectedEnvironment, EnvironmentDefinition, ReadingBoundary, ConditionalRegion
from src.reading.coverage import ReadingCoverage
from src.reading.dispatcher import StructuralDispatcher
from src.reading.options import OptionScope
from src.reading.tex_reader import CatCode, TexReader, TokenKind


class EnvironReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def setup_reader(self, source, *, loaded=True, catalog=None):
        self.resolver = BindingResolver(catalog or self.catalog)
        if loaded:
            self.assertTrue(self.resolver.load_package("environ"))
        self.context = self.resolver.new_context()
        self.reader = TexReader(source, source_id="paper.tex", occurrence_id=1,
                                catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.dispatcher = StructuralDispatcher(self.reader, self.context, self.resolver,
                                               source_commands=True, preparation=True)

    def complete(self):
        items = list(self.dispatcher)
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items), items[-1:])
        self.coverage = ReadingCoverage(self.reader.basis, items)
        return items

    def test_declaration_signature_defaults_final_code_and_exact_spans(self):
        source = r"\NewEnviron{samplebox}[2][{a]b}]{#1:#2:\BODY}[\unknown{final}]TAIL"
        self.setup_reader(source)
        definition = self.dispatcher.next_item()
        self.assertIsInstance(definition, EnvironmentDefinition)
        self.assertEqual(definition.name, "samplebox")
        self.assertEqual(definition.parameter_count, 2)
        self.assertEqual(self.reader.source_slice(definition.optional_default.span), "{a]b}")
        self.assertEqual(self.reader.source_slice(definition.body), r"#1:#2:\BODY")
        self.assertEqual(self.reader.source_slice(definition.final_code.span), r"\unknown{final}")
        self.assertEqual(self.reader.source_slice(definition.closing), r"}[\unknown{final}]")
        self.assertEqual(definition.body_name, "BODY")
        self.assertEqual(definition.default_final_commands, ())
        self.assertEqual(definition.target_check, "unverified")
        self.assertIs(self.context.lookup_environment("samplebox"), definition)
        self.assertIs(self.context.lookup_meaning("samplebox"), definition)
        self.assertIs(self.context.lookup_meaning("endsamplebox"), definition)
        self.assertIsNotNone(definition.unit_id)
        self.assertEqual(self.reader.position, source.index("TAIL"))

    def test_default_final_behavior_is_binding_data_not_synthetic_source(self):
        self.setup_reader(r"\NewEnviron{samplebox}{\BODY}")
        definition, = self.complete()[:1]
        self.assertIsNone(definition.final_code)
        self.assertEqual(definition.default_final_commands, ("ignorespacesafterend",))
        self.assertEqual(self.coverage.stored_definitions, (definition,))
        self.assertEqual(tuple(self.coverage.query("definition", part="body").matches), (definition.body,))

    def test_declaration_does_not_execute_processing_default_or_final_code(self):
        self.setup_reader(r"\newif\ifflag\flagtrue"
                          r"\NewEnviron{samplebox}[1][\flagfalse]{\makeatletter\def\nested##1{##1}\BODY}[\flagfalse]"
                          r"\ifflag YES\else NO\fi")
        self.complete()
        self.assertTrue(self.context.lookup_meaning("ifflag").truth)
        self.assertIsNone(self.context.lookup_meaning("ifflag").uncertain)
        self.assertIsNone(self.context.lookup_definition("nested"))
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_renewal_scope_restores_previous_environment(self):
        self.setup_reader(r"\NewEnviron{samplebox}{old}{\RenewEnviron{samplebox}[1]{new#1}}\begin{samplebox}TEXT\end{samplebox}")
        items = self.complete()
        definitions = [i for i in items if isinstance(i, EnvironmentDefinition)]
        self.assertEqual(definitions[1].target_check, "known_present")
        self.assertIs(self.context.lookup_environment("samplebox"), definitions[0])
        body = next(i for i in items if isinstance(i, CollectedEnvironment))
        self.assertEqual(body.definition_id, definitions[0].unit_id)

    def test_scoped_settings_are_snapshotted_by_each_declaration(self):
        self.setup_reader(r"\NewEnviron{first}{\BODY}"
                          r"{\environbodyname\CONTENT\environfinalcode{\finish}"
                          r"\NewEnviron{inner}{\CONTENT}}\NewEnviron{last}{\BODY}")
        items = self.complete()
        first, inner, last = [i for i in items if isinstance(i, EnvironmentDefinition)]
        self.assertEqual([d.body_name for d in (first, inner, last)], ["BODY", "CONTENT", "BODY"])
        self.assertEqual([t.value for t in inner.final_code.tokens], ["finish"])
        self.assertIsNone(last.final_code)
        self.assertIsNone(self.context.lookup_environment("inner"))
        self.assertIsNone(self.context.lookup_meaning("inner"))
        self.assertIsNone(self.context.lookup_capture_setting("packages/environ/body_name"))

    def test_later_settings_do_not_retroactively_change_captures(self):
        self.setup_reader(r"\environfinalcode{\first}\NewEnviron{samplebox}{\BODY}"
                          r"\environfinalcode{}\environbodyname{\NEXT}")
        self.complete()
        definition = self.context.lookup_environment("samplebox")
        self.assertEqual(definition.body_name, "BODY")
        self.assertEqual([t.value for t in definition.final_code.tokens], ["first"])
        copy = self.context.copy()
        self.context.push_scope()
        self.context.record_capture_setting("packages/environ/final_code", definition.final_code)
        self.context.restore_from(copy)
        self.assertEqual(self.context.lookup_capture_setting("packages/environ/final_code").tokens, ())

    def test_explicit_empty_final_overrides_configured_default(self):
        self.setup_reader(r"\environfinalcode{\finish}\NewEnviron{samplebox}{\BODY}[]")
        self.complete()
        definition = self.context.lookup_environment("samplebox")
        self.assertEqual(definition.final_code.tokens, ())
        self.assertEqual(definition.default_final_commands, ())

    def test_binding_must_be_activated(self):
        self.setup_reader(r"\NewEnviron{samplebox}{\BODY}", loaded=False)
        item = self.dispatcher.next_item()
        self.assertEqual(item.reason, "package_not_loaded")
        self.assertIsNone(self.context.lookup_environment("samplebox"))

    def test_known_duplicate_is_not_installed(self):
        self.setup_reader(r"\NewEnviron{samplebox}{old}\NewEnviron{samplebox}{new}")
        items = list(self.dispatcher)
        self.assertEqual(items[-1].reason, "definition_conflict")
        self.assertIs(self.context.lookup_environment("samplebox"), items[0])
        self.setup_reader(r"\NewEnviron{verbatim}{body}")
        self.assertEqual(self.dispatcher.next_item().reason, "definition_conflict")

    def test_native_box_primitive_cannot_be_declared_as_new_environment(self):
        self.setup_reader(r"\NewEnviron{box}{\BODY}")
        self.assertEqual(self.dispatcher.next_item().reason, "definition_conflict")
        self.assertIsNone(self.context.lookup_environment("box"))

    def test_unbound_renewal_is_captured_with_unverified_precondition(self):
        self.setup_reader(r"\RenewEnviron{publisher}{\BODY}")
        definition = self.complete()[0]
        self.assertEqual(definition.target_requirement, "present")
        self.assertEqual(definition.target_check, "unverified")

    def test_collector_keeps_arguments_in_body_until_later_interpretation(self):
        source = r"\NewEnviron{samplebox}[2][default]{#1#2\BODY}\begin{samplebox}[custom]{second}  text  \end{samplebox}TAIL"
        self.setup_reader(source)
        items = self.complete()
        region = next(i for i in items if isinstance(i, CollectedEnvironment))
        self.assertEqual(self.reader.source_slice(region.body), "[custom]{second}  text  ")
        self.assertEqual(self.reader.source_slice(region.opening), r"\begin{samplebox}")
        self.assertEqual(self.reader.source_slice(region.closing), r"\end{samplebox}")
        self.assertEqual(region.definition_id, items[0].unit_id)
        self.assertEqual(region.reason, "environment_interpretation")
        self.assertTrue(all(t.span.basis is self.reader.basis for t in region.tokens))

    def test_nested_begins_and_grouped_delimiters_use_token_collection(self):
        body = r"{\end{samplebox}}\def\x{\end{samplebox}}\begin{other}nested\end{different}\begin{samplebox}inner\end{samplebox}"
        self.setup_reader(r"\NewEnviron{samplebox}{\BODY}\begin{samplebox}" + body + r"\end{samplebox}")
        region = next(i for i in self.complete() if isinstance(i, CollectedEnvironment))
        self.assertEqual(self.reader.source_slice(region.body), body)
        # Delimiters of nested names remain real tokens, not reconstructed text.
        self.assertEqual(sum(t.catcode == CatCode.BEGIN_GROUP for t in region.tokens), 8)
        self.assertIsNone(self.context.lookup_definition("x"))

    def test_collection_never_dispatches_verbatim_or_conditionals(self):
        for prefix in (r"\verb|", r"\iffalse "):
            self.setup_reader(r"\NewEnviron{samplebox}{\BODY}\begin{samplebox}" + prefix + r"\end{samplebox}")
            region = next(i for i in self.complete() if isinstance(i, CollectedEnvironment))
            self.assertEqual(self.reader.source_slice(region.body), prefix)

    def test_collection_keeps_definition_time_categories_and_does_not_apply_effects(self):
        self.setup_reader(r"\NewEnviron{samplebox}{\BODY}\begin{samplebox}\catcode`\!=11\relax !\makeatletter @\end{samplebox}")
        region = next(i for i in self.complete() if isinstance(i, CollectedEnvironment))
        self.assertEqual(self.context.catcodes["!"], CatCode.OTHER)
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
        self.assertTrue(all(t.catcode == CatCode.OTHER for t in region.tokens if t.value in ("!", "@") and t.kind == TokenKind.CHARACTER))

    def test_comments_and_paragraphs_use_the_mouth_without_source_loss(self):
        body = "a% hidden \\end{samplebox}\r\nb\n\n c"
        self.setup_reader(r"\NewEnviron{samplebox}{\BODY}\begin{samplebox}" + body + r"\end{samplebox}")
        region = next(i for i in self.complete() if isinstance(i, CollectedEnvironment))
        self.assertEqual(self.reader.source_slice(region.body), body)
        self.assertEqual([t.value for t in region.tokens], ["a", "b", " ", "par", "c"])

    def test_invocation_invalidates_boolean_knowledge_but_declaration_does_not(self):
        self.setup_reader(r"\newif\ifflag\NewEnviron{samplebox}{\flagtrue}\begin{samplebox}body\end{samplebox}\ifflag X\fi")
        items = list(self.dispatcher)
        self.assertTrue(any(isinstance(i, ConditionalRegion) for i in items))
        self.assertIsNotNone(self.context.lookup_meaning("ifflag").uncertain)

    def test_stored_skipped_and_deferred_declarations_do_not_install(self):
        self.setup_reader(r"\def\stored{\NewEnviron{a}{\BODY}}\iffalse\NewEnviron{b}{\BODY}\fi"
                          r"\begin{unknown}\NewEnviron{c}{\end{unknown}}\end{unknown}")
        self.complete()
        for name in ("a", "b", "c"):
            self.assertIsNone(self.context.lookup_environment(name))

    def test_existing_collector_inside_deferred_environment_protects_whole_body(self):
        self.setup_reader(r"\NewEnviron{samplebox}{\BODY}\begin{unknown}\begin{samplebox}"
                          r"\end{unknown}\end{samplebox}\end{unknown}TAIL")
        # The collector uses its own nesting rules; an unmatched end cannot be
        # ignored merely because it would help an enclosing envelope.
        self.assertEqual(list(self.dispatcher)[-1].reason, "mismatched_environment")

    def test_nested_collection_protects_grouped_outer_delimiters(self):
        self.setup_reader(r"\NewEnviron{samplebox}{\BODY}\begin{unknown}\begin{samplebox}"
                          r"{\end{unknown}}\end{samplebox}later\end{unknown}TAIL")
        items = self.complete()
        region = next(i for i in items if getattr(i, "reason", None) == "environment_binding")
        self.assertEqual(self.reader.source_slice(region.span),
                         r"\begin{unknown}\begin{samplebox}{\end{unknown}}\end{samplebox}later\end{unknown}")

    def test_deferred_redefinition_cannot_reuse_the_previous_collector(self):
        self.setup_reader(r"\NewEnviron{samplebox}{\BODY}\begin{unknown}\RenewEnviron{samplebox}{\BODY}"
                          r"\begin{samplebox}text\end{samplebox}\end{unknown}")
        self.assertEqual(list(self.dispatcher)[-1].reason, "environment_reading")

    def test_existing_end_command_is_a_new_environment_conflict(self):
        self.setup_reader(r"\def\endsamplebox{original}\NewEnviron{samplebox}{\BODY}")
        self.assertEqual(list(self.dispatcher)[-1].reason, "definition_conflict")
        self.assertIsNone(self.context.lookup_environment("samplebox"))

    def test_author_redefinition_of_entry_or_exit_blocks_old_collector(self):
        for name in ("samplebox", "endsamplebox"):
            self.setup_reader("\\NewEnviron{samplebox}{\\BODY}\\renewcommand{\\" + name + r"}{}\begin{samplebox}body\end{samplebox}")
            self.assertEqual(list(self.dispatcher)[-1].reason, "stored_macro")

    def test_parameterless_option_declaration_reuses_token_cursor(self):
        self.setup_reader(r"\DeclareOption{x}{\NewEnviron{samplebox}{\BODY}}\ProcessOptions")
        self.dispatcher.options = OptionScope("local", requested_options(self.context, ("x",)))
        self.complete()
        self.assertIsInstance(self.context.lookup_environment("samplebox"), EnvironmentDefinition)

    def test_option_invocation_is_not_silently_treated_as_executed(self):
        self.setup_reader(r"\NewEnviron{samplebox}{\BODY}\DeclareOption{x}{\begin{samplebox}text\end{samplebox}}\ProcessOptions")
        self.dispatcher.options = OptionScope("local", requested_options(self.context, ("x",)))
        self.assertEqual(list(self.dispatcher)[-1].reason, "option_body")

    def test_malformed_or_computed_declarations_are_explicit_boundaries(self):
        cases = (
            (r"\NewEnviron*{samplebox}{x}", "argument_required"),
            (r"\NewEnviron{\name}{x}", "computed_argument"),
            (r"\NewEnviron{endsamplebox}{x}", "environment_name"),
            (r"\NewEnviron{samplebox}[\n]{x}", "unsupported_definition_count"),
            (r"\NewEnviron{samplebox}[0][x]{x}", "invalid_definition_default"),
            (r"\NewEnviron{samplebox}[1]{#2}", "invalid_definition_parameter"),
            (r"\NewEnviron{samplebox}{x}[#1]", "invalid_definition_parameter"),
            (r"\NewEnviron{samplebox}{x}[", "unclosed_argument"),
            (r"\environbodyname{\csname X\endcsname}", "computed_argument"),
        )
        for source, reason in cases:
            with self.subTest(source=source):
                self.setup_reader(source)
                self.assertEqual(self.dispatcher.next_item().reason, reason)
                self.assertIsNone(self.context.lookup_environment("samplebox"))

    def test_malformed_collections_keep_located_remainder(self):
        for ending, reason in (("", "unclosed_environment"), (r"\end{other}", "mismatched_environment"),
                               (r"\end\name", "argument_required")):
            self.setup_reader(r"\NewEnviron{samplebox}{\BODY}\begin{samplebox}body" + ending)
            item = list(self.dispatcher)[-1]
            self.assertEqual(item.reason, reason)
            self.assertTrue(self.reader.source_slice(item.remainder).startswith(r"\begin{samplebox}"))

    def test_schema_and_command_identity_are_declarative(self):
        catalog = deepcopy(self.catalog)
        commands = catalog.package_bindings["environ"]["reading"]["commands"]
        commands[0]["name"] = r"\DeclareBox"
        commands[0]["metadata"]["default_body_name"] = "CONTENT"
        self.setup_reader(r"\DeclareBox{samplebox}{\CONTENT}", catalog=reload_catalog(self, catalog))
        self.assertEqual(self.complete()[0].body_name, "CONTENT")
        for key, value in (("default_body_name", None), ("default_final_commands", "bad"),
                           ("collector", {"handler": "unknown"})):
            reading = deepcopy(self.catalog.package_bindings["environ"]["reading"])
            reading["commands"][0]["metadata"][key] = value
            with self.subTest(key=key), self.assertRaises(ProfileError):
                self.catalog._validate_reading(reading, Path("environ.yaml"))


class EnvironPreparationTests(unittest.TestCase):
    def setUp(self):
        root = PROJECT / "temp/tests"
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8", newline="\n")

    def test_local_style_preserves_option_boolean_through_environ_declaration(self):
        style = (r"\newif\ifload\loadtrue\RequirePackage{environ}"
                 r"\NewEnviron{ack}{\section*{Acknowledgments}\BODY}"
                 r"\ifload\RequirePackage{natbib}\fi")
        source = (r"\documentclass{article}\usepackage{local}\begin{document}"
                  r"\begin{ack}  THANKS  \end{ack}\input{later}\citep{a}\bibliography{refs}\end{document}")
        self.put("local.sty", style)
        self.put("main.tex", source)
        self.put("later.tex", "LATER")
        self.put("refs.bib", "@misc{a,title={A}}")
        with patch("subprocess.run", side_effect=AssertionError("No compiler in preparation")):
            text, manifest, out, ledger = preprocess_paper(str(self.root))
        self.assertFalse(manifest.unresolved)
        self.assertIn("natbib", [p.name for p in manifest.packages_declared])
        self.assertIn(r"\begin{ack}  THANKS  \end{ack}", text)
        self.assertIn("LATER", text)
        self.assertIn(r"\bibitem", text)
        self.assertTrue((out / "bibliography.bib").is_file())
        self.assertEqual((out / "local.sty").read_text(), style)
        self.assertEqual((self.root / "main.tex").read_text(), source)
        self.assertFalse(any(c["unaccounted"] for c in ledger.source_coverage))
        self.assertEqual(len(set(manifest.source_reads)), len(manifest.source_reads))
        region, = [r for r in manifest.requirements if r["reason"] == "environment_interpretation"]
        units = {u["id"]:u for u in manifest.units}
        self.assertEqual(units[region["definition_unit_id"]]["kind"], "EnvironmentDefinition")
        self.assertEqual(region["locations"][0]["artifact"], "master.tex")
        self.assertEqual(units[region["definition_unit_id"]]["locations"][0]["artifact"], "local.sty")

    def test_default_and_final_dependencies_are_surveyed_without_execution(self):
        self.put("main.tex", r"\documentclass{article}\usepackage{environ}"
                 r"\NewEnviron{samplebox}[1][\input{default}]{\input{body}\BODY}[\input{final}]TAIL")
        text, manifest, _, _ = preprocess_paper(str(self.root))
        report = next(r for r in manifest.source_survey if r["source"] == "main.tex")
        self.assertEqual([c["context"] for c in report["commands"] if c["name"] == "input"],
                         ["stored_definition_default", "stored_definition", "stored_definition_final"])
        self.assertFalse(manifest.unresolved)
        self.assertIn("TAIL", text)


if __name__ == "__main__":
    unittest.main()
