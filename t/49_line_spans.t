use strict;
use warnings;
use Test::More;
use Encode qw(encode);
use Scalar::Util qw(refaddr);
use LaTeXML::Core::SourceRegistry;

# Expected graphemes and byte widths are explicit, independent of the engine's
# decoder and grapheme-to-span implementation. Every case has a nonzero offset.
my @cases = (
  ['ASCII', 'ab ', 'UTF-8', 1, 'ab ', ['a', 'b', ' '], [1, 1, 1], 0],
  ['singleton Unicode', encode('UTF-8', "\x{e9}\x{1f642}"), 'UTF-8', 1,
    "\x{e9}\x{1f642}", ["\x{e9}", "\x{1f642}"], [2, 4], 0],
  ['combining accent', encode('UTF-8', "a\x{301}b"), 'UTF-8', 1,
    "a\x{301}b", ["a\x{301}", 'b'], [3, 1], 0],
  ['leading combining mark', encode('UTF-8', "\x{301}a"), 'UTF-8', 1,
    "\x{301}a", ["\x{301}", 'a'], [2, 1], 0],
  ['emoji joiner', encode('UTF-8', "\x{1f469}\x{200d}\x{1f4bb}!"), 'UTF-8', 1,
    "\x{1f469}\x{200d}\x{1f4bb}!", ["\x{1f469}\x{200d}\x{1f4bb}", '!'], [11, 1], 0],
  ['regional pair', encode('UTF-8', "\x{1f1fa}\x{1f1f8}x"), 'UTF-8', 1,
    "\x{1f1fa}\x{1f1f8}x", ["\x{1f1fa}\x{1f1f8}", 'x'], [8, 1], 0],
  ['Hangul cluster', encode('UTF-8', "\x{1100}\x{1161}\x{11a8}!"), 'UTF-8', 1,
    "\x{1100}\x{1161}\x{11a8}!", ["\x{1100}\x{1161}\x{11a8}", '!'], [9, 1], 0],
  ['emoji modifier', encode('UTF-8', "\x{1f44d}\x{1f3fd}!"), 'UTF-8', 1,
    "\x{1f44d}\x{1f3fd}!", ["\x{1f44d}\x{1f3fd}", '!'], [8, 1], 0],
  ['space with accent', encode('UTF-8', " \x{301}  "), 'UTF-8', 1,
    " \x{301}  ", [" \x{301}", ' ', ' '], [3, 1, 1], 0],
  ['malformed group', "a\xe2\x82b", 'UTF-8', 1, 'a b', ['a', ' ', 'b'], [1, 2, 1], 1],
  ['substituted cluster', encode('UTF-8', "\x{fffd}\x{301}b"), 'UTF-8', 1,
    " \x{301}b", [" \x{301}", 'b'], [5, 1], 1],
  ['unsubstituted replacement', encode('UTF-8', "\x{fffd}b"), 'UTF-8', 0,
    "\x{fffd}b", ["\x{fffd}", 'b'], [3, 1], 0],
  ['disabled decoding', "\xc3\xa9", undef, 1, "\xc3\xa9", ["\xc3", "\xa9"], [1, 1], 0],
  ['other codec', "caf\xe9", 'cp1252', 1, "caf\x{e9}", ['c', 'a', 'f', "\x{e9}"], [1, 1, 1, 1], 0],
  ['empty line', '', 'UTF-8', 1, '', [], [], 0],
);
for my $case (@cases) {
  my ($name, $raw, $encoding, $substitute, $text, $graphemes, $widths, $substitutions) = @$case;
  my $registry = LaTeXML::Core::SourceRegistry->new();
  my $id = $registry->registerSource(kind => 'literal', raw => "prefix\r\n$raw\nsuffix\n",
    encoding => $encoding, substitute => $substitute);
  my @lines = $registry->getLines($id);
  my $record = $lines[1];
  my ($cursor, @spans) = (8);
  for my $width (@$widths) {
    push @spans, {byteStart => $cursor, byteEnd => $cursor + $width};
    $cursor += $width;
  }
  is($record->{decoded}, $text, "$name: decoded text");
  is_deeply($record->{graphemes}, $graphemes, "$name: grapheme boundaries");
  is_deeply($record->{spans}, \@spans, "$name: exact absolute byte intervals");
  cmp_ok($record->{substitutions}, '==', $substitutions, "$name: substitution count");
  is($cursor, $record->{rawContentEnd}, "$name: spans cover the complete content");
  my %addresses;
  ok(!(grep { $addresses{refaddr($_)}++ } @{$record->{spans}}), "$name: each grapheme owns a distinct span hash");
  if ($substitutions) {
    my @events = $registry->getEncodingEvents;
    my ($start, $end) = $name eq 'malformed group' ? (9, 11) : (8, 11);
    is_deeply(\@events, [{sourceId => $id, byteStart => $start, byteEnd => $end, replacement => 'U+0020'}],
      "$name: event owns replacement bytes, not the whole grapheme");
    $record->{spans}[0]{byteEnd} = 999;
    $record->{spans}[1]{byteEnd} = 999 if @{$record->{spans}} > 1;
    is($events[0]{byteEnd}, $end, "$name: retained events do not alias line spans");
  }
}

# A line can be decoded again under another active encoding. Its old spans and
# other source records remain independently owned, including singleton lines.
{
  my $registry = LaTeXML::Core::SourceRegistry->new();
  my $id = $registry->registerSource(kind => 'literal', raw => "caf\xc3\xa9\nnext\n", encoding => undef);
  my ($record, $next) = $registry->getLines($id);
  my $old = $record->{spans};
  $registry->decodeLine($id, $record, 'UTF-8');
  is(scalar(@$old), 5, 'old byte-wise spans survive redecoding');
  is_deeply($record->{spans}, [{byteStart => 0, byteEnd => 1}, {byteStart => 1, byteEnd => 2},
      {byteStart => 2, byteEnd => 3}, {byteStart => 3, byteEnd => 5}], 'redecoding maps the new encoding');
  $old->[0]{byteEnd} = 999;
  is($record->{spans}[0]{byteEnd}, 1, 'redecoding owns fresh span hashes');
  is($next->{spans}[0]{byteEnd}, 7, 'other lines remain independent');
}

# Mouth transformations operate on separate hashes, while the registry keeps
# the original line. Trimming, synthetic EOLs and ^^ splices must preserve it.
{
  my $registry = LaTeXML::Core::SourceRegistry->new();
  my $id = $registry->registerSource(kind => 'literal', raw => "^^61x  \r\n");
  my ($record) = $registry->getLines($id);
  my @expected = map { +{byteStart => $_, byteEnd => $_ + 1} } 0 .. 6;
  my @mouths = map { bless {source => 'virtual.tex', source_id => $id, current_line_record => $record},
    'LaTeXML::Core::Mouth' } 1 .. 2;
  $_->_prepareCaptureLine($record->{decoded}, "\r") for @mouths;
  is_deeply($mouths[0]{capture_spans}, [@expected[0 .. 4], {byteStart => 7, byteEnd => 9, synthetic => 1}],
    'file mouth trims spaces and adds the raw CRLF synthetic span');
  $mouths[0]->_spliceCaptureSpans(0, 4);
  is_deeply($mouths[0]{capture_spans}, [{byteStart => 0, byteEnd => 4}, $expected[4],
      {byteStart => 7, byteEnd => 9, synthetic => 1}], 'TeX hex splice owns its complete original interval');
  $mouths[0]{capture_spans}[1]{byteEnd} = 999;
  is_deeply($record->{spans}, \@expected, 'mouth splicing and mutation preserve the registry spans');
  is($mouths[1]{capture_spans}[4]{byteEnd}, 5, 'another mouth keeps independent span hashes');
  my $literal = bless {source => '', source_id => $id, current_line_record => $record}, 'LaTeXML::Core::Mouth';
  $literal->_prepareCaptureLine($record->{decoded}, undef);
  is_deeply($literal->{capture_spans}, \@expected, 'literal mouth retains trailing spaces without a synthetic endline');
  my $off = bless {capture_spans => ['stale']}, 'LaTeXML::Core::Mouth';
  $off->_prepareCaptureLine('', undef);
  ok(!defined $off->{capture_spans}, 'uncaptured input has no capture spans');
}
done_testing();
