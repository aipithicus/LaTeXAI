"""Ordered, non-expanding key/value configuration and named recipes.

Bindings own namespaces, scopes, supported keys and mutually exclusive effects.
Stored recipes keep tokens; applying a recipe resolves references at that point.
"""
from dataclasses import dataclass

from .contracts import ReadingIssue, ScannedArgument
from .tex_reader import CatCode, TokenKind
from .argument_scanner import key_values


@dataclass(frozen=True, slots=True)
class ConfiguredOptions:
    values: dict
    unclassified: tuple[str, ...] = ()


def configured_options(profile, argument, context, *, preserve_unclassified=False):
    if not profile.configuration:
        return ConfiguredOptions(key_values(argument))
    contract, state = profile.configuration, context.configurations
    values = state.resolve(contract['namespace'], entries(argument), contract,
                           preserve_unclassified=preserve_unclassified)
    return ConfiguredOptions(state.reading_values(values, contract), state.unclassified(values, contract))


@dataclass(frozen=True, slots=True)
class OptionEntry:
    key: str
    value: ScannedArgument | None  # A bare key uses its binding-declared default.


def _trim(tokens):
    first, end = 0, len(tokens)
    while first < end and tokens[first].catcode == CatCode.SPACE:
        first += 1
    while end > first and tokens[end - 1].catcode == CatCode.SPACE:
        end -= 1
    return tokens[first:end]


def entries(argument):
    """Split only category-12 separators at group depth zero, retaining order."""
    if argument is None:
        return ()
    chunks, chunk, depth = [], [], 0
    for token in argument.tokens:
        if token.catcode == CatCode.BEGIN_GROUP:
            depth += 1
        elif token.catcode == CatCode.END_GROUP:
            depth -= 1
        if token.kind == TokenKind.CHARACTER and token.catcode == CatCode.OTHER and token.value == ',' and depth == 0:
            chunks.append(chunk)
            chunk = []
        else:
            chunk.append(token)
    chunks.append(chunk)
    result = []
    for chunk in chunks:
        chunk = _trim(chunk)
        if not chunk:
            continue
        depth, separator = 0, None
        for i, token in enumerate(chunk):
            if token.catcode == CatCode.BEGIN_GROUP:
                depth += 1
            elif token.catcode == CatCode.END_GROUP:
                depth -= 1
            elif depth == 0 and token.kind == TokenKind.CHARACTER and token.catcode == CatCode.OTHER and token.value == '=':
                separator = i
                break
        key_tokens = chunk if separator is None else chunk[:separator]
        try:
            key = ScannedArgument('option key', argument.span, tuple(key_tokens)).literal()
        except ReadingIssue as error:
            raise ReadingIssue('computed_option', 'Option names require literal characters') from error
        if not key:
            raise ReadingIssue('computed_option', 'An option needs a literal key')
        value = None
        if separator is not None:
            tokens = _trim(chunk[separator + 1:])
            start = tokens[0].span.start if tokens else chunk[separator].span.end
            end = tokens[-1].span.end if tokens else start
            # keyval removes one encompassing group, not all braces in a value.
            depth, enclosing = 0, bool(tokens and tokens[0].catcode == CatCode.BEGIN_GROUP)
            for i, token in enumerate(tokens):
                depth += (token.catcode == CatCode.BEGIN_GROUP) - (token.catcode == CatCode.END_GROUP)
                if depth == 0 and i < len(tokens) - 1:
                    enclosing = False
            if enclosing:
                start, end = tokens[0].span.end, tokens[-1].span.start
                tokens = tokens[1:-1]
            value = ScannedArgument(key, argument.span.basis.span(start, end), tuple(tokens))
        result.append(OptionEntry(key, value))
    return tuple(result)


def literal_value(entry, contract):
    if entry.value is None:
        defaults = contract.get('bare_defaults', {})
        if entry.key not in defaults:
            raise ReadingIssue('configuration_value', f'{entry.key!r} needs a value')
        return defaults[entry.key]
    tokens = entry.value.tokens
    if any(t.kind != TokenKind.CHARACTER or t.catcode in (CatCode.ACTIVE, CatCode.PARAMETER) for t in tokens):
        raise ReadingIssue('computed_option', f'{entry.key!r} requires expansion')
    return ''.join(t.value for t in tokens)


class ConfigurationState:
    """Document-local namespace tables with group journals and global definitions."""
    def __init__(self):
        self.values = {}
        self.styles = {}
        self.scopes = []

    def copy(self):
        other = ConfigurationState()
        other.values = {key: dict(value) for key, value in self.values.items()}
        other.styles = dict(self.styles)
        other.scopes = [(dict(values), dict(styles)) for values, styles in self.scopes]
        return other

    def push(self):
        self.scopes.append(({}, {}))

    def pop(self):
        for table, saved in zip((self.values, self.styles), self.scopes.pop()):
            for key, previous in saved.items():
                if previous is None:
                    table.pop(key, None)
                else:
                    table[key] = previous

    def store(self, table_name, key, value, scope):
        table = getattr(self, table_name)
        index = 0 if table_name == 'values' else 1
        if scope == 'global':
            for saved in self.scopes:
                saved[index].pop(key, None)
        elif scope == 'local':
            if self.scopes:
                self.scopes[-1][index].setdefault(key, table.get(key))
        else:
            raise ReadingIssue('configuration_scope', 'Unknown configuration scope')
        table[key] = value

    @staticmethod
    def name(value, contract):
        if contract['name_normalization'] == 'lowercase_no_spaces':
            return ''.join(value.split()).lower()
        return value.strip()

    def resolve(self, namespace, incoming, contract, *, preserve_unclassified=False):
        """Iterative depth-first recipe application; no recursion or execution."""
        result = dict(self.values.get(namespace, {}))
        stack = [(iter(incoming), ())]
        neutral = set(contract.get('non_reading_options', ()))
        keys = contract.get('reading_affecting_keys', {})
        while stack:
            iterator, chain = stack[-1]
            entry = next(iterator, None)
            if entry is None:
                stack.pop()
                continue
            if entry.key == contract['style_key']:
                name = self.name(literal_value(entry, contract), contract)
                if name in chain:
                    raise ReadingIssue('configuration_cycle', f'Cyclic named configuration: {chain + (name,)}')
                recipe = self.styles.get((namespace, name))
                if recipe is None:
                    raise ReadingIssue('configuration_missing', f'No captured configuration {name!r} in {namespace}')
                stack.append((iter(recipe), chain + (name,)))
                continue
            if entry.key not in keys and entry.key not in neutral and not preserve_unclassified:
                raise ReadingIssue('unsupported_reading_option', f'Unclassified option {entry.key!r}')
            # Non-reading and unclassified values stay tokens, never execution.
            if entry.key in keys:
                literal_value(entry, contract)
            for group in contract.get('exclusive_keys', ()):
                if entry.key in group:
                    for old in group:
                        result.pop(old, None)
            result[entry.key] = entry
        if not preserve_unclassified and (unknown := self.unclassified(result, contract)):
            raise ReadingIssue('unsupported_reading_option', f'Unclassified options: {", ".join(unknown)}')
        return result

    @staticmethod
    def unclassified(values, contract):
        """Unrecognized values stay token data, never implicit neutral settings."""
        known = set(contract.get('reading_affecting_keys', ())) | set(contract.get('non_reading_options', ()))
        return tuple(key for key in values if key not in known)

    @staticmethod
    def reading_values(values, contract):
        return {key: literal_value(entry, contract) for key, entry in values.items()
                if key in contract.get('reading_affecting_keys', {})}
