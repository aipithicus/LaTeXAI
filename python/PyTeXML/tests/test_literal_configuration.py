"""Bounded configuration expectations from listings.sty/lstmisc.sty.

Authority: lstset (402-404), DefDriver (294-319), NormedDef (466), and
lstmisc's style/escape aspects. No TeX executable is required by these tests.
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.reading.character_rules import ProfileError
from src.reading.contracts import LiteralRegion, ReadingBoundary
from src.reading.coverage import ReadingCoverage
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import CatCode, TexReader
from src.prepare.pipeline import preprocess_paper


def listing(body='code', options=''):
    return r'\begin{lstlisting}' + ('[' + options + ']' if options else '') + '\n' + body + '\n' + r'\end{lstlisting}' + '\n'


class LiteralConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def read(self, source, *, preparation=True, catalog=None, active=True):
        self.resolver = BindingResolver(catalog or self.catalog)
        if active:
            self.resolver.load_package('listings')
        self.context = self.resolver.new_context()
        self.reader = TexReader(source, catcodes=self.context.catcodes, endline_char=self.context.endlinechar,
                                source_id='paper.tex', occurrence_id=7)
        self.dispatcher = StructuralDispatcher(self.reader, self.context, self.resolver,
                                               preparation=preparation, source_commands=True)
        self.items = list(self.dispatcher)
        return self.items

    def complete(self, source, **kwargs):
        items = self.read(source, **kwargs)
        self.assertFalse([i for i in items if isinstance(i, ReadingBoundary)])
        self.assertEqual(self.reader.text, source)
        return [i for i in items if isinstance(i, LiteralRegion)]

    def settings(self):
        return self.context.configurations.values.get('packages/listings', {})

    def test_named_recipe_keeps_tokens_and_is_not_applied_when_defined(self):
        source = r'\newif\ifkeep\keeptrue\lstdefinestyle{stored}{basicstyle={\keepfalse},escapeinside=\later}\ifkeep YES\else NO\fi'
        self.complete(source)
        self.assertEqual(self.settings(), {})
        recipe = self.context.configurations.styles['packages/listings', 'stored']
        self.assertEqual(recipe[0].value.tokens[0].value, 'keepfalse')
        self.assertEqual(recipe[1].value.tokens[0].value, 'later')
        self.assertTrue(self.context.lookup_meaning('ifkeep').truth)

    def test_configuration_requires_active_package(self):
        item = self.read(r'\lstset{escapechar=|}', active=False)[-1]
        self.assertIsInstance(item, ReadingBoundary)
        self.assertEqual(item.reason, 'package_not_loaded')

    def test_scoped_settings_restore_outer_configuration(self):
        source = r'\lstset{escapeinside={(*}{*)}}{' + r'\lstset{escapechar=|}' + listing('|inner|') + '}' + listing('(*outer*)')
        inner, outer = self.complete(source)
        self.assertEqual([self.reader.source_slice(r.interpolations[0].span) for r in (inner, outer)], ['|inner|', '(*outer*)'])
        self.assertEqual(set(self.settings()), {'escapeinside'})
        self.assertEqual(self.context.scope_depth, 0)

    def test_named_definitions_are_global_but_their_application_is_local(self):
        source = r'{\lstdefinestyle{My Style}{escapechar=|}\lstset{style=my style}}' + listing('|ordinary|') + r'\lstset{style=MY STYLE}' + listing('|escaped|')
        plain, escaped = self.complete(source)
        self.assertFalse(plain.interpolations)
        self.assertEqual(len(escaped.interpolations), 1)

    def test_styles_resolve_in_order_and_at_application_time(self):
        source = (r'\lstdefinestyle{base}{escapechar=|}\lstdefinestyle{child}{style=base}'
                  r'\lstset{style=child}\lstdefinestyle{base}{escapechar=!}' + listing('|old|') +
                  r'\lstset{style=child}' + listing('!new!') +
                  r'\lstset{escapechar=|,style=base,escapechar=?}' + listing('?last?'))
        regions = self.complete(source)
        self.assertEqual([self.reader.source_slice(r.interpolations[0].span) for r in regions], ['|old|', '!new!', '?last?'])

    def test_local_options_override_without_changing_defaults(self):
        source = r'\lstset{escapechar=|}' + listing('!local!', 'escapechar=!') + listing('|global|')
        regions = self.complete(source)
        self.assertEqual([self.reader.source_slice(r.interpolations[0].span) for r in regions], ['!local!', '|global|'])

    def test_style_selection_is_an_overlay_not_a_reset(self):
        self.complete(r'\lstset{escapechar=|}\lstdefinestyle{layout}{numbers=left}\lstset{style=layout}' + listing('|keep|'))
        self.assertEqual(set(self.settings()), {'numbers', 'escapechar'})

    def test_grouped_values_comments_and_duplicate_keys(self):
        source = '\\lstset{caption={A,B=C},basicstyle={\\ttfamily},% ignored =,\n escapechar=!,escapechar=|}' + listing('|ok|')
        self.complete(source)
        self.assertEqual(''.join(t.value for t in self.settings()['caption'].value.tokens), 'A,B=C')
        self.assertEqual(self.settings()['basicstyle'].value.tokens[0].value, 'ttfamily')

    def test_empty_setting_and_empty_recipe_are_noops(self):
        self.complete(r'\lstset{}\lstdefinestyle{empty}{}\lstset{style=empty}')
        self.assertEqual(self.settings(), {})

    def test_empty_escape_value_disables_inherited_escape(self):
        regions = self.complete(r'\lstset{escapeinside={(*}{*)}}' + listing('(*plain*)', 'escapeinside={}') + listing('(*escape*)'))
        self.assertFalse(regions[0].interpolations)
        self.assertEqual(len(regions[1].interpolations), 1)

    def test_invalid_application_is_atomic(self):
        for options, reason in [('unknown=x', 'unsupported_reading_option'),
                                ('escapechar=LONG', 'unsupported_reading_option'),
                                ('escapeinside=\\computed', 'computed_option'),
                                ('style=missing', 'configuration_missing'),
                                ('escapechar', 'configuration_value')]:
            with self.subTest(options=options):
                items = self.read(r'\lstset{escapechar=|}\lstset{numbers=left,' + options + '}')
                self.assertEqual(items[-1].reason, reason)
                self.assertEqual(set(self.settings()), {'escapechar'})

    def test_unknown_style_keys_are_deferred_until_application(self):
        self.complete(r'\lstdefinestyle{future}{unknown=anything}')
        self.assertEqual(self.read(r'\lstdefinestyle{future}{unknown=x}\lstset{style=future}')[-1].reason, 'unsupported_reading_option')

    def test_cycles_and_missing_forward_references_are_explicit(self):
        source = r'\lstdefinestyle{a}{style=b}\lstdefinestyle{b}{style=a}\lstset{style=a}'
        self.assertEqual(self.read(source)[-1].reason, 'configuration_cycle')
        self.assertEqual(self.settings(), {})

    def test_global_redefinition_survives_group_exit(self):
        source = r'\lstdefinestyle{x}{escapechar=|}{\lstdefinestyle{x}{escapechar=!}}\lstset{style=x}' + listing('!new!')
        self.assertEqual(len(self.complete(source)[0].interpolations), 1)

    def test_copy_restore_keeps_independent_configuration_journals(self):
        self.complete(r'\lstset{escapechar=|}')
        saved = self.context.copy()
        self.context.push_scope()
        self.context.configurations.store('values', 'packages/listings', {}, 'local')
        self.context.restore_from(saved)
        self.assertEqual(set(self.settings()), {'escapechar'})
        self.assertEqual(self.context.scope_depth, 0)
        self.context.configurations.values.clear()
        self.assertTrue(saved.configurations.values)

    def test_stored_and_skipped_bodies_do_not_install_configuration(self):
        source = r'\def\later{\lstset{escapechar=|}}\iffalse\lstdefinestyle{x}{escapechar=!}\lstset{style=x}\fi' + listing('|plain|')
        self.assertFalse(self.complete(source)[0].interpolations)
        self.assertEqual(self.settings(), {})
        self.assertEqual(self.context.configurations.styles, {})

    def test_unbound_environment_configuration_does_not_leak(self):
        item = self.read(r'\begin{unknown}\lstset{escapechar=|}\end{unknown}')[-1]
        self.assertEqual(item.reason, 'environment_reading')
        self.assertFalse(self.settings())

    def test_dialects_parents_and_aspect_loading_remain_explicit(self):
        for source in (r'\lstdefinestyle[d]{x}{escapechar=|}',
                       r'\lstdefinestyle{x}[d]{base}{escapechar=|}',
                       r'\lstdefinestyle{x}{escapechar=|}[extra]'):
            with self.subTest(source=source):
                self.assertEqual(self.read(source)[-1].reason, 'configuration_header')
                self.assertFalse(self.context.configurations.styles)

    def test_header_catcodes_are_temporary_and_binding_declared(self):
        source = r'\catcode`\==13 \lstset{basicstyle={\a@b},escapechar=|}'
        self.complete(source)
        self.assertEqual(self.context.catcodes['='], CatCode.ACTIVE)
        self.assertEqual(self.context.catcodes['@'], CatCode.OTHER)
        self.assertEqual(self.settings()['basicstyle'].value.tokens[0].value, 'a@b')

    def test_configuration_commands_can_be_renamed_by_yaml(self):
        catalog = deepcopy(self.catalog)
        for command in catalog.package_bindings['listings']['reading']['commands']:
            if command['name'] == r'\lstset':
                command['name'] = r'\ConfigureCode'
        regions = self.complete(r'\ConfigureCode{escapechar=|}' + listing('|ok|'), catalog=catalog)
        self.assertEqual(len(regions[0].interpolations), 1)

    def test_definition_scope_is_selected_by_yaml(self):
        catalog = deepcopy(self.catalog)
        catalog.package_bindings['listings']['reading']['configuration']['definition_scope'] = 'local'
        self.complete(r'{\lstdefinestyle{local}{escapechar=|}}', catalog=catalog)
        self.assertFalse(self.context.configurations.styles)

    def test_bare_boolean_and_explicit_false_are_captured(self):
        self.complete(r'\lstset{mathescape}\lstset{mathescape=false}' + listing('$literal$'))
        self.assertEqual(self.settings()['mathescape'].value.literal(), 'false')

    def test_multiple_escapes_crlf_and_control_symbol_close(self):
        body = r'|\| not closed here | code |two|' + '\n% literal'
        source = r'\lstset{escapechar=|}' + listing(body).replace('\n', '\r\n')
        region = self.complete(source)[0]
        self.assertEqual(len(region.interpolations), 2)
        self.assertIn(r'\| not closed here', self.reader.source_slice(region.interpolations[0].span))

    def test_invalid_configuration_schema_is_rejected(self):
        for key, value in [('definition_scope', 'magic'), ('namespace', ''), ('exclusive_keys', [['unknown', 'escapechar']]),
                           ('bare_defaults', {'unknown': True})]:
            reading = deepcopy(self.catalog.package_bindings['listings']['reading'])
            reading['configuration'][key] = value
            with self.subTest(key=key), self.assertRaises(ProfileError):
                self.catalog._validate_reading(reading, Path('listings.yaml'))

    def test_literal_interpolation_spans_units_and_coverage(self):
        source = r'\lstset{escapeinside={(*}{*)}}' + listing('code (*\\textbf{X}*) more') + 'TAIL'
        region = self.complete(source)[0]
        child = region.interpolations[0]
        self.assertEqual(self.reader.source_slice(child.span), r'(*\textbf{X}*)')
        self.assertIsNotNone(child.unit_id)
        coverage = ReadingCoverage(self.reader.basis, self.items)
        self.assertTrue(coverage.unknown.covers(child.span))
        self.assertFalse(coverage.query('literal').matches.intersection(coverage.unknown))
        self.assertEqual(self.context.catcodes['*'], CatCode.OTHER)

    def test_comment_hides_escape_closer_and_fake_environment_end(self):
        body = '(*% *) hidden closer\n\\end{lstlisting}\n real *) code'
        region = self.complete(r'\lstset{escapeinside={(*}{*)}}' + listing(body))[0]
        self.assertIn(r'\end{lstlisting}', self.reader.source_slice(region.interpolations[0].span))
        self.assertIn('real *)', self.reader.source_slice(region.interpolations[0].span))

    def test_interpolation_is_not_executed_and_invalidates_boolean_knowledge(self):
        source = r'\newif\ifkeep\keeptrue\lstset{escapechar=|}' + listing(r'|\keepfalse\input{missing}|') + r'\ifkeep A\fi'
        items = self.read(source)
        self.assertEqual(items[-1].reason, 'uncertain_boolean')
        self.assertTrue(self.context.lookup_meaning('ifkeep').truth)

    def test_strict_dispatch_does_not_claim_interpolation_execution(self):
        items = self.read(r'\lstset{escapeinside={(*}{*)}}' + listing('(*text*)'), preparation=False)
        self.assertEqual(items[-1].reason, 'unsupported_literal_grammar')

    def test_unclosed_escape_preserves_listing_residue(self):
        source = r'\lstset{escapeinside={(*}{*)}}' + listing('(* missing')
        item = self.read(source)[-1]
        self.assertEqual(item.reason, 'unclosed_interpolation')
        self.assertEqual(self.reader.source_slice(item.remainder), listing('(* missing'))


class ConfigurationPreparationTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'temp/tests'
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def put(self, name, text):
        (self.root / name).write_text(text, encoding='utf-8', newline='')

    def prepare(self, body):
        self.put('main.tex', '\\documentclass{article}\n\\usepackage{listings}\n\\begin{document}\n' + body + '\n\\end{document}')
        return preprocess_paper(str(self.root), root_tex='main.tex')

    def test_multifile_style_capture_listing_and_later_bibliography(self):
        self.put('settings.tex', r'\lstdefinestyle{code}{basicstyle={\ttfamily},escapeinside={(*}{*)}}\lstset{style=code}')
        self.put('child.tex', 'CHILD')
        self.put('refs.bib', '@article{a,title={Entry},author={Author},year={2024}}')
        block = listing(r'(*\textbf{inside}*) % code  ')
        text, manifest, out, ledger = self.prepare(r'\input{settings}' + block + r'\input{child}\cite{a}\bibliography{refs}')
        self.assertIn(block, text)
        self.assertIn('CHILD', text)
        self.assertIn(r'\bibitem', text)
        self.assertTrue((out / 'bibliography.bib').exists())
        required = [r for r in manifest.requirements if r['reason'] == 'literal_interpolation']
        self.assertEqual(len(required), 1)
        self.assertEqual(required[0]['location_status'], 'mapped')
        location = required[0]['locations'][0]
        self.assertEqual(text[location['start']:location['end']], r'(*\textbf{inside}*)')
        self.assertEqual(len(manifest.source_reads), len(set(manifest.source_reads)))
        self.assertIn(block, (self.root / 'main.tex').read_text())

    def test_global_settings_are_respected_for_external_listing(self):
        self.put('code.txt', '|escaped|')
        text, manifest, out, _ = self.prepare(r'\lstset{escapechar=|}\lstinputlisting{code.txt}')
        self.assertEqual(manifest.resources[0]['disposition'], 'retained')
        self.assertIn('literal-resources/code.txt', text)
        self.assertEqual((out / 'literal-resources/code.txt').read_text(), '|escaped|')

    def test_escape_dependency_is_recorded_but_not_executed(self):
        block = listing(r'|\input{missing}|')
        text, manifest, _, _ = self.prepare(r'\lstset{escapechar=|}' + block + 'AFTER')
        self.assertIn(block, text)
        self.assertIn('AFTER', text)
        required = [r for r in manifest.requirements if r['reason'] == 'deferred_dependency']
        self.assertEqual(len(required), 1)
        self.assertEqual(required[0]['stage'], 'preparation')
        self.assertEqual(manifest.preparation_status, 'partial')
        self.assertEqual(required[0]['location_status'], 'mapped')

    def test_style_option_is_kept_on_inline_external_resource(self):
        self.put('code.txt', 'code')
        text, manifest, _, _ = self.prepare(r'\lstdefinestyle{code}{numbers=left}\lstinputlisting[style=code]{code.txt}')
        self.assertEqual(manifest.resources[0]['disposition'], 'inlined')
        self.assertIn(r'\begin{lstlisting}[style=code]', text)


if __name__ == '__main__':
    unittest.main()
