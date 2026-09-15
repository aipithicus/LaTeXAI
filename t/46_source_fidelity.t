use strict;
use warnings;
use Test::More;
use FindBin;
use File::Spec;
use File::Temp qw(tempdir);
use Cwd qw(abs_path);
use Encode qw(encode decode FB_DEFAULT);
use XML::LibXML;
use LaTeXML::Core;
use LaTeXML::Core::Mouth::file;
use lib File::Spec->catdir($FindBin::Bin, '..', 'tools', 'dev');
use CaptureAudit qw(run_conversion write_raw);

chdir File::Spec->catdir($FindBin::Bin, '..') or die $!;
my $temp = abs_path(tempdir('source-fidelity-XXXXXX', DIR => 'temp/t', CLEANUP => 1));
my $capture_ns = 'http://dlmf.nist.gov/LaTeXML/capture';
my $ltx_ns = 'http://dlmf.nist.gov/LaTeXML';
my $serial = 0;

sub read_lines {
  my ($capture, $raw, $encodings) = @_;
  my $path = "$temp/reader-" . ++$serial . '.tex';
  # Keep adversarial octets in a text file; the normal Mouth rejects binary files.
  write_raw($path, $raw . ('ASCII text witness ' x 20) . "\n");
  my $core = LaTeXML::Core->new(capture => $capture, verbosity => -2);
  local $LaTeXML::Global::STATE = $core->{state};
  my $state = $core->{state};
  my $registry = LaTeXML::Core::SourceRegistry->new(root_kind => 'file', root_request => $path);
  $state->assignValue(SOURCE_REGISTRY => $registry, 'global') if $capture;
  my $mouth = LaTeXML::Core::Mouth::file->new($path);
  my (@lines, @records, @infos);
  for my $encoding (@$encodings) {
    $state->assignValue(PERL_INPUT_ENCODING => $encoding, 'global');
    $mouth->{lineno}++;
    push @lines, $mouth->getNextLine;
    push @records, $mouth->{current_line_record} if $capture;
    push @infos, $state->getStatus('info') || 0;
  }
  $mouth->finish;
  return { lines => \@lines, infos => \@infos, records => \@records,
    events => [$registry->getEncodingEvents] };
}

# The active setting can change while an already-open file is being read.
# CR-only input also buffers several logical lines in one native read.
for my $newline ("\n", "\r\n", "\r") {
  my $raw = join($newline, "Journ\xc3\xa9e", "Journ\xc3\xa9e", "caf\xe9") . $newline;
  my $off = read_lines(0, $raw, [undef, 'utf-8', 'cp1252']);
  my $on = read_lines(1, $raw, [undef, 'utf-8', 'cp1252']);
  is_deeply($off->{lines}, ["Journ\xc3\xa9e", "Journ\x{e9}e", "caf\x{e9}"], 'ordinary reader follows the active encoding');
  is_deeply($on->{lines}, $off->{lines}, 'capture follows each logical line encoding, including disabled decoding');
  is_deeply($on->{infos}, $off->{infos}, 'encoding changes preserve diagnostic counts');
  is(scalar(@{ $on->{events} }), 0, 'valid bytes in their active encodings create no substitution events');
  is(scalar(@{ $on->{records}[0]{spans} }), 8, 'disabled decoding maps the two UTF-8 octets separately');
  is(scalar(@{ $on->{records}[1]{spans} }), 7, 'enabled UTF-8 maps the accented scalar once');
}

# Encode is the ordinary reader's decoding contract, including how many
# malformed octets one replacement consumes. Expectations name exact spans.
for my $case (
  ['isolated', 'c3', 1], ['truncated', 'e282', 2], ['surrogate', 'eda080', 3],
  ['overlong', 'f0808080', 4], ['out-of-range', 'f4908080', 4],
  ['literal-replacement', 'efbfbd', 3]) {
  my ($name, $hex, $width) = @$case;
  my $raw = 'a' . pack('H*', $hex) . "b\n";
  my $off = read_lines(0, $raw, ['utf-8']);
  my $on = read_lines(1, $raw, ['utf-8']);
  is_deeply($off->{lines}, ['a b'], "$name ordinary substitution is one space");
  is_deeply($on->{lines}, $off->{lines}, "$name capture decoding agrees");
  is_deeply($on->{infos}, [1], "$name capture emits one diagnostic for the line");
  is_deeply($on->{infos}, $off->{infos}, "$name diagnostic parity");
  is(scalar(@{ $on->{events} }), 1, "$name has one encoding event");
  is_deeply([@{ $on->{events}[0] }{qw(byteStart byteEnd)}], [1, 1 + $width], "$name event owns the exact malformed byte group");
  is_deeply($on->{records}[0]{spans}[1], { byteStart => 1, byteEnd => 1 + $width }, "$name replacement span matches the decoder");
}
{
  my $raw = encode('UTF-8', "a\x{301}\x{1f642}z\n");
  my $off = read_lines(0, $raw, ['utf-8']);
  my $on = read_lines(1, $raw, ['utf-8']);
  is_deeply($on->{lines}, $off->{lines}, 'valid combining and supplementary scalars agree');
  is_deeply($on->{records}[0]{spans}, [
      { byteStart => 0, byteEnd => 3 }, { byteStart => 3, byteEnd => 7 }, { byteStart => 7, byteEnd => 8 }],
    'grapheme mapping owns each actual UTF-8 interval');
  is_deeply($on->{infos}, [0], 'valid Unicode has no diagnostic');
}
for my $capture (0, 1) {
  my $core = LaTeXML::Core->new(capture => $capture, verbosity => -2);
  local $LaTeXML::Global::STATE = $core->{state};
  my $registry = LaTeXML::Core::SourceRegistry->new();
  $core->{state}->assignValue(SOURCE_REGISTRY => $registry, 'global') if $capture;
  my $mouth = LaTeXML::Core::Mouth->new("a\xc3\nb\xc3", source_kind => 'literal');
  is($core->{state}->getStatus('info') || 0, 1, "string capture=$capture reports once per open, not per line");
  is_deeply([$mouth->getNextLine, $mouth->getNextLine], ['a ', 'b '], "string capture=$capture substitution matches");
  $mouth->finish;
  my $unicode = "already decoded \x{fffd}";
  $mouth = LaTeXML::Core::Mouth->new($unicode, source_kind => 'literal');
  is($mouth->getNextLine, $unicode, "string capture=$capture preserves already-decoded replacement scalar");
  is($core->{state}->getStatus('info') || 0, 1, "string capture=$capture does not diagnose already-decoded text");
  $mouth->finish;
}

sub convert {
  my ($path, $capture) = @_;
  my $result = run_conversion({ texpath => $path, options => {
      capture => $capture, preload => ['LaTeX.pool'], searchpaths => [$temp],
      includecomments => 1, includepathpis => 0, verbosity => -2 } }, "$temp/convert-" . ++$serial);
  ok(!$result->{failure}, 'fresh conversion succeeds');
  is($result->{status_code}, 0, 'fixture has no engine warnings or errors');
  return $result;
}

for my $newline ("\n", "\r\n", "\r") {
  my $equation = join($newline, '\begin{equation}', '\begin{aligned}',
    'a&=b' . chr(92) . chr(92), 'c&=d', '\end{aligned}', '\end{equation}');
  my $bracket = join($newline, '\[', 'e=f', '\]');
  my $callsite = '\whole{g' . $newline . '+h}';
  my $source = join($newline, '\documentclass{article}', '\usepackage{amsmath}',
    '\newcommand{\whole}[1]{$#1$}', '\begin{document}', $equation, $bracket,
    '$inline$', $callsite, '\end{document}', '');
  my $path = "$temp/roundtrip-" . ++$serial . '.tex';
  write_raw($path, $source);
  my $off = convert($path, 0);
  my $on = convert($path, 1);
  is($on->{stripped}, $off->{stripped}, 'live off/on trees agree for each source line ending');
  my $doc = XML::LibXML->load_xml(string => encode('UTF-8', $on->{raw}), keep_blanks => 1, load_ext_dtd => 0);
  my %seen;
  for my $math ($doc->getElementsByTagNameNS($ltx_ns, 'Math')) {
    my $kind = $math->getAttributeNS($capture_ns, 'provenance');
    ok($kind eq 'source' || $kind eq 'callsite-only', 'every test Math has an exact source or callsite interval');
    next unless $kind eq 'source' || $kind eq 'callsite-only';
    my ($start_key, $end_key, $slice_key) = $kind eq 'source'
      ? qw(byteStart byteEnd source) : qw(callsiteStart callsiteEnd callsite);
    my $start = $math->getAttributeNS($capture_ns, $start_key);
    my $end = $math->getAttributeNS($capture_ns, $end_key);
    my $slice = $math->getAttributeNS($capture_ns, $slice_key);
    is($slice, substr($source, $start, $end - $start), 'serialized capture attribute round-trips to the actual source bytes');
    $seen{$slice}++;
  }
  cmp_ok($seen{$equation} || 0, '>=', 2, 'nested aligned carriers retain the complete enclosing equation');
  is($seen{$bracket} || 0, 1, 'bracket display retains exact delimiters and line endings');
  is($seen{'$inline$'} || 0, 1, 'inline math remains exact');
  is($seen{'\whole'} || 0, 1, 'author command callsite remains exact');
  ok(index($on->{raw}, '&#13;') >= 0, 'CR is escaped in actual Core serialization') if $newline =~ /\r/;
}
{
  my $source = "\\documentclass{article}\n\\usepackage[ansinew]{inputenc}\n\\begin{document}\n"
    . "% Journ\xc3\xa9e\nText \$a=b\$.\n\\end{document}\n";
  my $path = "$temp/encoding-switch.tex";
  write_raw($path, $source);
  my $off = convert($path, 0);
  my $on = convert($path, 1);
  is($on->{stripped}, $off->{stripped}, 'inputenc changing the open Mouth preserves comment and document parity');
}
for my $value ("a\r\n\tb", 'literal &#13; & " < >') {
  my $xml = '<node value="' . LaTeXML::Core::Document::serialize_attr($value) . '"/>';
  my $doc = XML::LibXML->load_xml(string => $xml);
  is($doc->documentElement->getAttribute('value'), $value, 'ordinary attributes preserve CR and literal entities too');
}
done_testing();
