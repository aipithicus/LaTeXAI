# -*- CPERL -*-
#**********************************************************************
# Capture provenance, byte custody, ledger, and schema contracts
#**********************************************************************
use strict;
use warnings;

use Test::More;
use Cwd qw(abs_path);
use Digest::SHA qw(sha256_hex);
use Encode qw(decode encode FB_DEFAULT);
use File::Spec;
use File::Temp qw(tempdir);
use File::Path qw(make_path);
use POSIX ();
use FindBin;
use IPC::Open3;
use Symbol qw(gensym);
use XML::LibXML;
use XML::LibXML::XPathContext;
use JSON::PP ();
use LaTeXAI::Post::Markdown;

use LaTeXML::Core;
use LaTeXML::Core::Token;
use LaTeXML::Core::Tokens;

my $LTX_NS     = 'http://dlmf.nist.gov/LaTeXML';
my $CAPTURE_NS = 'http://dlmf.nist.gov/LaTeXML/capture';
my $CD_NS      = 'http://dlmf.nist.gov/LaTeXML/cd';
my $ROOT        = abs_path(File::Spec->catdir($FindBin::Bin, '..'));
my $FIXTURES    = File::Spec->catdir($ROOT, 't', 'capture');
my $TEMP        = tempdir('latexml-capture-XXXXXX', TMPDIR => 1, CLEANUP => 1);
my $RUNSTAMP    = $ENV{LATEXAI_RUNSTAMP} || POSIX::strftime('%Y%m%d_%H%M%S', localtime);
my $CAPTURE_OFF_SHA256 = 'e3e9a5333291657d3de1f8ff9f8c85146ddd2ccf3582d09e12173530d67cb927';

chdir($ROOT) or die "Cannot enter $ROOT: $!";

sub slurp_raw {
  my ($path) = @_;
  open(my $in, '<:raw', $path) or die "Cannot read $path: $!";
  local $/;
  my $content = <$in>;
  close($in);
  return $content; }

sub write_raw {
  my ($path, $content) = @_;
  open(my $out, '>:raw', $path) or die "Cannot write $path: $!";
  print {$out} $content;
  close($out);
  return; }

sub capture_decode {
  my ($bytes) = @_;
  my $copy = $bytes;
  my $decoded = decode('UTF-8', $copy, FB_DEFAULT);
  $decoded =~ s/\x{FFFD}/ /g;
  return $decoded; }

sub xpath {
  my ($document) = @_;
  my $xc = XML::LibXML::XPathContext->new($document);
  $xc->registerNs(ltx     => $LTX_NS);
  $xc->registerNs(capture => $CAPTURE_NS);
  $xc->registerNs(cd      => $CD_NS);
  return $xc; }

sub cattr {
  my ($node, $name) = @_;
  return $node->getAttributeNS($CAPTURE_NS, $name); }

sub convert_document {
  my ($request, %options) = @_;
  my $capture = exists $options{capture} ? delete $options{capture} : 1;
  my $preload = delete $options{preload} || ['LaTeX.pool'];
  my $core = LaTeXML::Core->new(
    preload        => $preload,
    searchpaths    => [$FIXTURES],
    capture        => $capture,
    includecomments => 0,
    includepathpis  => 0,
    verbosity       => -2,
    %options,
  );
  my $document = eval { $core->convertFile($request) };
  die "Conversion failed for $request: $@" unless $document;
  return ($document, $core); }

sub normalized_capture_xml {
  my ($document) = @_;
  my $parser = XML::LibXML->new(no_blanks => 1);
  my $copy = $parser->load_xml(string => $document->toString(0));
  my $xc = xpath($copy);
  my ($root) = $xc->findnodes('/ltx:document');
  $root->setAttributeNS($CAPTURE_NS, 'capture:base', 'CAPTURE_BASE')
    if $root->hasAttributeNS($CAPTURE_NS, 'base');
  my ($engine) = $xc->findnodes('/ltx:document/capture:ledger/capture:engine');
  $engine->setAttribute(revision => 'CAPTURE_REVISION') if $engine;
  return $copy->toStringC14N(0); }

sub fixture_document {
  my ($name, @flags) = @_;
  my $output = File::Spec->catfile($TEMP, join('-', $name, @flags) . '.xml');
  my ($status, $messages) = run_command($^X, '-I', File::Spec->catdir($ROOT, 'lib'),
    File::Spec->catfile($ROOT, 'tools', 'dev', 'capture-fixture.pl'), @flags,
    File::Spec->catfile($FIXTURES, "$name.tex"), $output);
  is($status, 0, "$name @flags converts without errors or warnings") or diag($messages);
  return XML::LibXML->load_xml(location => $output); }

sub without_capture {
  my ($document) = @_;
  my $copy = $document->cloneNode(1);
  foreach my $node (xpath($copy)->findnodes('/ltx:document/capture:ledger')) {
    my $indent = $node->previousSibling;
    $indent->unbindNode if $indent && $indent->nodeType == XML_TEXT_NODE && $indent->data =~ /^\s*$/;
    $node->unbindNode; }
  foreach my $attr (xpath($copy)->findnodes('//@capture:*')) {
    $attr->ownerElement->removeAttributeNS($CAPTURE_NS, $attr->localname); }
  foreach my $text (xpath($copy)->findnodes('//text()')) {
    $text->unbindNode if $text->data =~ /^\s*$/; }
  my $xml = $copy->toString(0);
  $xml =~ s/ xmlns:capture="\Q$CAPTURE_NS\E"//g;
  return $xml; }

sub resolved_capture_file {
  my ($document, $file) = @_;
  my $root = $document->documentElement;
  my $base = cattr($root, 'base');
  return unless defined $base && length($base) && defined $file && length($file);
  my $path = File::Spec->catfile($base, split(m{/}, $file));
  return abs_path($path); }

sub assert_file_is_portable {
  my ($document, $file, $label) = @_;
  unlike($file, qr{\\}, "$label uses normalized separators");
  ok(!File::Spec->file_name_is_absolute($file), "$label is relative to capture:base");
  my $base = abs_path(cattr($document->documentElement, 'base'));
  my $path = resolved_capture_file($document, $file);
  ok(defined $path && -f $path, "$label resolves to a live source file");
  my $canon_base = lc(File::Spec->canonpath($base));
  my $canon_path = lc(File::Spec->canonpath($path || ''));
  my $prefix = $canon_base . ($canon_base =~ /[\\\/]$/ ? '' : '\\');
  ok($canon_path eq $canon_base || index($canon_path, $prefix) == 0,
    "$label resolves beneath capture:base");
  return $path; }

sub assert_source_bytes {
  my ($document, $math, $label) = @_;
  is(cattr($math, 'provenance'), 'source', "$label is source-backed");
  my $file = cattr($math, 'file');
  my $path = assert_file_is_portable($document, $file, "$label file");
  my $raw = slurp_raw($path);
  my ($start, $end) = (0 + cattr($math, 'byteStart'), 0 + cattr($math, 'byteEnd'));
  ok($start >= 0 && $start <= $end && $end <= length($raw), "$label interval is in bounds");
  my $slice = substr($raw, $start, $end - $start);
  is(capture_decode($slice), cattr($math, 'source'), "$label decoded source matches retained bytes");
  return ($raw, $start, $end, $slice); }

# Complements assert_source_bytes: the interval may match the file and still
# name the wrong construct (a later callsite). This checks authorship.
sub assert_owns_slice {
  my ($document, $carrier, $expected, $label) = @_;
  is(cattr($carrier, 'source'), $expected, "$label recorded slice is the author's construct");
  return; }

sub assert_partition {
  my ($document, $label) = @_;
  my $xc = xpath($document);
  my @math = $xc->findnodes('//ltx:Math');
  my ($ledger) = $xc->findnodes('/ltx:document/capture:ledger/capture:math');
  ok($ledger, "$label has a math ledger");
  my %seen = (source => 0, 'callsite-only' => 0, 'cross-source' => 0, unlocated => 0);
  foreach my $math (@math) {
    my $kind = cattr($math, 'provenance');
    ok(exists $seen{$kind}, "$label carrier has exactly one recognized provenance: $kind");
    $seen{$kind}++ if exists $seen{$kind}; }
  is(0 + $ledger->getAttribute('total'), scalar(@math), "$label ledger total matches DOM carriers");
  is(0 + $ledger->getAttribute('source'), $seen{source}, "$label source partition matches");
  is(0 + $ledger->getAttribute('callsiteOnly'), $seen{'callsite-only'}, "$label callsite partition matches");
  is(0 + $ledger->getAttribute('crossSource'), $seen{'cross-source'}, "$label cross-source partition matches");
  is(0 + $ledger->getAttribute('unlocated'), $seen{unlocated}, "$label unlocated partition matches");
  is(0 + $ledger->getAttribute('total'),
    $seen{source} + $seen{'callsite-only'} + $seen{'cross-source'} + $seen{unlocated},
    "$label partition arithmetic is exact");
  return; }

sub run_command {
  my (@command) = @_;
  my ($child_in, $child_out);
  my $child_err = gensym;
  my $pid = open3($child_in, $child_out, $child_err, @command);
  close($child_in);
  local $/;
  my $stdout = <$child_out> // '';
  my $stderr = <$child_err> // '';
  close($child_out);
  close($child_err);
  waitpid($pid, 0);
  return ($? >> 8, $stdout . $stderr); }

sub validate_capture_document {
  my ($document, $name) = @_;
  my $input = File::Spec->catfile($TEMP, "$name.xml");
  my $output = File::Spec->catfile($TEMP, "$name-post.xml");
  write_raw($input, $document->isa('XML::LibXML::Document')
      ? $document->toString(1) : encode('UTF-8', $document->toString(1)));
  # Development-loop conventions (docs/testing.md): lib/ is the whole include
  # path (tools/dev/generate.pl puts the generated modules there), and every
  # CLI log goes under temp/logs/<runstamp>/ rather than the working directory.
  # The stamp is shared with the aliases through LATEXAI_RUNSTAMP when set.
  my $logdir = File::Spec->catdir($ROOT, 'temp', 'logs', $RUNSTAMP);
  make_path($logdir);
  my ($status, $messages) = run_command(
    $^X, '-I', File::Spec->catdir($ROOT, 'lib'),
    File::Spec->catfile($ROOT, 'bin', 'latexmlpost'), '--quiet', '--quiet', '--validate',
    '--log=' . File::Spec->catfile($logdir, "45_capture-$name.latexmlpost.log"),
    "--destination=$output", $input);
  is($status, 0, "$name passes latexmlpost --validate") or diag($messages);
  ok(-s $output, "$name validation produced a document");
  return; }

# Run the golden conversion first: loading the engine repeatedly in one Perl
# process can legitimately accumulate redefinition warnings in later States.
my ($crlf) = convert_document(File::Spec->catfile($FIXTURES, 'crlf.tex'));
my $crlf_xml = $crlf->getDocument;

# Cases 1-6 and 8-10: delimiter ownership, author expansion, and byte columns.
my ($positions, $positions_core) = convert_document(File::Spec->catfile($FIXTURES, 'positions.tex'));
my $positions_xml = $positions->getDocument;
my $positions_xc = xpath($positions_xml);
my @positions_math = $positions_xc->findnodes('//ltx:Math');
is(scalar(@positions_math), 12, 'positions fixture produces the expected carrier count');

my %by_source;
foreach my $math (@positions_math) {
  push(@{ $by_source{ cattr($math, 'source') || '' } }, $math); }

is(scalar(@{ $by_source{'$a=b$'} || [] }), 1, 'case 1 inline dollar carrier found');
assert_source_bytes($positions_xml, $by_source{'$a=b$'}[0], 'case 1 inline dollars');
is($by_source{'$a=b$'}[0]->getAttribute('mode'), 'inline', 'case 1 mode is inline');

is(scalar(@{ $by_source{'\[c=d\]'} || [] }), 1, 'case 2 bracket display carrier found');
assert_source_bytes($positions_xml, $by_source{'\[c=d\]'}[0], 'case 2 bracket display');
is($by_source{'\[c=d\]'}[0]->getAttribute('mode'), 'display', 'case 2 remains display source, not callsite');

is(scalar(@{ $by_source{'$$e=f$$'} || [] }), 1, 'case 3 double-dollar carrier found');
assert_source_bytes($positions_xml, $by_source{'$$e=f$$'}[0], 'case 3 double dollars');

my $outer_equation = "\\begin{equation}\n\\begin{aligned}\ng&=h\n\\end{aligned}\n\\end{equation}";
is(scalar(@{ $by_source{$outer_equation} || [] }), 3,
  'case 4 every MathFork carrier inherits the exact outer equation span');
foreach my $i (0 .. 2) {
  assert_source_bytes($positions_xml, $by_source{$outer_equation}[$i], "case 4 aligned carrier " . ($i + 1)); }

my @callsite = grep { cattr($_, 'provenance') eq 'callsite-only' } @positions_math;
is(scalar(@callsite), 1, 'case 5 has one callsite-only author-generated carrier');
is(cattr($callsite[0], 'callsite'), '\eq', 'case 5 callsite is the author macro token');
ok(!$callsite[0]->hasAttributeNS($CAPTURE_NS, 'source'), 'case 5 has no source slice');
ok(!$callsite[0]->hasAttributeNS($CAPTURE_NS, 'file'), 'case 5 has no source file attribute');
my $callsite_path = assert_file_is_portable($positions_xml, cattr($callsite[0], 'callsiteFile'),
  'case 5 callsite file');
my $callsite_raw = slurp_raw($callsite_path);
is(substr($callsite_raw, 0 + cattr($callsite[0], 'callsiteStart'),
    cattr($callsite[0], 'callsiteEnd') - cattr($callsite[0], 'callsiteStart')),
  '\eq', 'case 5 callsite byte interval is independently exact');

is(scalar(@{ $by_source{'$\KK$'} || [] }), 1, 'case 6 source math containing an author macro found');
assert_source_bytes($positions_xml, $by_source{'$\KK$'}[0], 'case 6 source with author macro');

my ($positions_raw, $multi_start) = assert_source_bytes(
  $positions_xml, $by_source{'$m=n$'}[0], 'case 8 multibyte prefix');
is($multi_start, index($positions_raw, encode('UTF-8', '$m=n$')),
  'case 8 byte start is independent of multibyte and grapheme columns');

assert_source_bytes($positions_xml, $by_source{'$^^41$'}[0], 'case 9 hexadecimal ^^ splice');
assert_source_bytes($positions_xml, $by_source{'$^^j$'}[0], 'case 9 three-character ^^ splice');
is($by_source{'$^^41$'}[0]->getAttribute('tex'), 'A', 'case 9 hexadecimal splice still expands normally');

my ($trailing_raw, undef, $trailing_end) = assert_source_bytes(
  $positions_xml, $by_source{'$o=p$'}[0], 'case 10 trailing spaces');
is(substr($trailing_raw, $trailing_end, 3), '   ', 'case 10 trailing spaces are outside the math interval');

assert_partition($positions_xml, 'positions fixture');
my ($positions_ledger) = $positions_xc->findnodes('/ltx:document/capture:ledger/capture:math');
is(0 + $positions_ledger->getAttribute('display'), 5, 'MathFork carriers count as display math');
is(0 + $positions_ledger->getAttribute('inline'), 7, 'remaining carriers count as inline math');
is($positions_ledger->getAttribute('parser'), 'run', 'parser execution is explicit');
ok($positions_ledger->hasAttribute('failedCells'), 'failedCells is present when parser ran');

# The checked-in golden normalizes only the portable base and build revision.
my $golden_path = File::Spec->catfile($FIXTURES, 'crlf.xml');
my $golden = XML::LibXML->load_xml(location => $golden_path);

# Case 7: exact CRLF custody and normalized golden comparison.
my $crlf_raw = slurp_raw(File::Spec->catfile($FIXTURES, 'crlf.tex'));
my $crlf_count = () = $crlf_raw =~ /\r\n/g;
(my $without_crlf = $crlf_raw) =~ s/\r\n//g;
is($crlf_count, 4, 'case 7 fixture retains four CRLF terminators');
unlike($without_crlf, qr/[\r\n]/, 'case 7 fixture has no normalized or bare line terminators');
my ($crlf_math) = xpath($crlf_xml)->findnodes('//ltx:Math');
assert_source_bytes($crlf_xml, $crlf_math, 'case 7 CRLF math');
my $normalized_crlf = normalized_capture_xml($crlf_xml);
my $normalized_golden = normalized_capture_xml($golden);
if ($normalized_crlf ne $normalized_golden) {
  my $at = 0;
  my $limit = length($normalized_crlf) < length($normalized_golden)
    ? length($normalized_crlf) : length($normalized_golden);
  $at++ while $at < $limit
    && substr($normalized_crlf, $at, 1) eq substr($normalized_golden, $at, 1);
  diag('golden divergence at byte ' . $at
      . '; live=' . substr($normalized_crlf, $at, 160)
      . '; expected=' . substr($normalized_golden, $at, 160)); }
is($normalized_crlf, $normalized_golden,
  'capture golden matches after base and revision normalization only');
assert_partition($crlf_xml, 'CRLF fixture');

# Case 11: a carrier crossing an input boundary retains both identities.
my ($cross) = convert_document(File::Spec->catfile($FIXTURES, 'cross-main.tex'));
my $cross_xml = $cross->getDocument;
my ($cross_math) = xpath($cross_xml)->findnodes('//ltx:Math');
is(cattr($cross_math, 'provenance'), 'cross-source', 'case 11 is classified cross-source');
ok(!$cross_math->hasAttributeNS($CAPTURE_NS, 'source'), 'case 11 has no fictitious contiguous slice');
my $cross_start_path = assert_file_is_portable($cross_xml, cattr($cross_math, 'startFile'),
  'case 11 start file');
my $cross_end_path = assert_file_is_portable($cross_xml, cattr($cross_math, 'endFile'),
  'case 11 end file');
is(substr(slurp_raw($cross_start_path), 0 + cattr($cross_math, 'byteStart'), 1), '$',
  'case 11 opening endpoint addresses the source dollar');
is(substr(slurp_raw($cross_end_path), cattr($cross_math, 'byteEnd') - 1, 1), '$',
  'case 11 closing endpoint addresses the included-source dollar');
assert_partition($cross_xml, 'cross-source fixture');

# Case 12: literal roots have stable identity without borrowing a file path.
my ($literal) = convert_document('literal:$l=m$');
my $literal_xml = $literal->getDocument;
my ($literal_math) = xpath($literal_xml)->findnodes('//ltx:Math');
is(cattr($literal_math, 'provenance'), 'source', 'case 12 literal math is source-backed');
is(cattr($literal_math, 'file'), 'literal', 'case 12 uses the literal sentinel');
is(cattr($literal_math, 'source'), '$l=m$', 'case 12 literal slice is exact');
ok(!$literal_xml->documentElement->hasAttributeNS($CAPTURE_NS, 'base'),
  'case 12 literal root omits capture:base');
assert_partition($literal_xml, 'literal fixture');

# Case 13: invalid UTF-8 is preserved as bytes and substituted as U+0020.
my $invalid_path = File::Spec->catfile($TEMP, 'invalid-utf8.tex');
my $invalid_prefix = encode('ASCII', "\\documentclass{article}\n\\begin{document}\nbad \$a+");
my $invalid_suffix = encode('ASCII', "=b\$\n\\end{document}\n");
write_raw($invalid_path, $invalid_prefix . chr(0xC3) . $invalid_suffix);
my ($invalid) = convert_document($invalid_path);
my $invalid_xml = $invalid->getDocument;
my $invalid_xc = xpath($invalid_xml);
my ($invalid_math) = $invalid_xc->findnodes('//ltx:Math');
is(cattr($invalid_math, 'source'), '$a+ =b$', 'case 13 capture source applies U+0020 substitution');
my ($invalid_event) = $invalid_xc->findnodes('/ltx:document/capture:ledger/capture:encoding/capture:event');
ok($invalid_event, 'case 13 records an encoding event');
is(0 + $invalid_event->getAttribute('byteStart'), length($invalid_prefix),
  'case 13 event starts at the malformed byte');
is(0 + $invalid_event->getAttribute('byteEnd'), length($invalid_prefix) + 1,
  'case 13 event consumes exactly one malformed byte');
is($invalid_event->getAttribute('replacement'), 'U+0020', 'case 13 event records the replacement scalar');
is(substr(slurp_raw($invalid_path), length($invalid_prefix), 1), chr(0xC3),
  'case 13 raw authority retains the malformed byte');
assert_source_bytes($invalid_xml, $invalid_math, 'case 13 invalid UTF-8 math');
assert_partition($invalid_xml, 'invalid UTF-8 fixture');

# Case 14: central package/class routing and request occurrences.
my ($routes) = convert_document(File::Spec->catfile($FIXTURES, 'routes.tex'), includestyles => 1);
my $routes_xml = $routes->getDocument;
my $routes_xc = xpath($routes_xml);
my @requests = $routes_xc->findnodes('/ltx:document/capture:ledger/capture:packages/capture:package');
my %requests = map { $_->getAttribute('name') => $_ } @requests;
# Transitive loads (a binding's RequirePackage) are ordinary, not diagnostics.
my @transitive = grep { ($_->getAttribute('requestOrigin') // '') eq 'transitive' } @requests;
ok(scalar(@transitive), 'case 14 records transitive package loads');
ok(!grep({ $_->hasAttribute('requestByteStart') } @transitive), 'case 14 transitive loads carry no request range');
is(scalar(grep { $_->hasAttribute('diagnostic') } @requests), 0, 'case 14 no ordinary request carries a diagnostic');
is(scalar(grep { ($_->getAttribute('requestOrigin') // '') eq 'source' } @requests), 4,
  'case 14 the four document requests are source-origin');
foreach my $name (qw(capture-special capturebinding captureraw capturemissing)) {
  ok($requests{$name}, "case 14 records $name"); }
is($requests{'capture-special'}->getAttribute('kind'), 'class', 'case 14 records the requested kind');
is($requests{'capture-special'}->getAttribute('route'), 'binding', 'case 14 class fallback uses binding route');
like(($requests{'capture-special'}->getAttribute('resolved') =~ s!\\!/!gr), qr{(?:^|/)capture\.cls\.ltxml$},
  'case 14 class fallback records its actual resolution');
is($requests{capturebinding}->getAttribute('route'), 'binding', 'case 14 package binding route');
is($requests{captureraw}->getAttribute('route'), 'raw', 'case 14 raw style route');
is($requests{capturemissing}->getAttribute('route'), 'missing', 'case 14 missing route');
my $routes_raw = slurp_raw(File::Spec->catfile($FIXTURES, 'routes.tex'));
foreach my $name (qw(capture-special capturebinding captureraw capturemissing)) {
  my $request = $requests{$name};
  ok($request->hasAttribute('requestByteStart') && $request->hasAttribute('requestByteEnd'),
    "case 14 $name has a request occurrence range");
  my $request_slice = substr($routes_raw, 0 + $request->getAttribute('requestByteStart'),
    $request->getAttribute('requestByteEnd') - $request->getAttribute('requestByteStart'));
  like($request_slice, qr/^\\(?:documentclass|usepackage)$/, "case 14 $name range addresses its request token"); }
assert_partition($routes_xml, 'package-route fixture');

# Case 15: tikz-cd arrows carry explicit, parser-stable edge metadata.
my ($tikzcd) = convert_document(File::Spec->catfile($ROOT, 't', 'tikz-cd', 'tikzcd.tex'));
my $tikzcd_xml = $tikzcd->getDocument;
my $tikzcd_xc = xpath($tikzcd_xml);
my @diagrams = $tikzcd_xc->findnodes('//ltx:XMArray');
is(scalar(@diagrams), 2, 'case 15 preserves both commutative-diagram arrays');
my @diagram_meanings = $tikzcd_xc->findnodes(
  '//ltx:XMApp[ltx:XMTok[@meaning="commutative-diagram"] and ltx:XMRef]');
is(scalar(@diagram_meanings), 2, 'case 15 preserves each array datameaning');
my @arrows = $tikzcd_xc->findnodes('//ltx:XMApp[@role="ARROW" and @cd:from]');
is(scalar(@arrows), 7, 'case 15 emits seven structured diagram edges');
foreach my $arrow (@arrows) {
  foreach my $name (qw(from to dir label labelpos style)) {
    ok($arrow->hasAttributeNS($CD_NS, $name), "case 15 every edge carries cd:$name"); } }
my %edges = map { $_->getAttributeNS($CD_NS, 'label') => $_ } @arrows;
my %expected_edges = (
  f => ['1-1', '1-2', 'r',  'above', 'plain'],
  g => ['1-1', '2-1', 'd',  'below', 'plain'],
  h => ['1-2', '2-2', 'd',  'above', 'plain'],
  k => ['2-1', '2-2', 'r',  'above', 'plain'],
  '\qlabel' => ['1-1', '2-2', 'r',  'below', 'bend left=30,shift right=1ex,hook,Rightarrow'],
  p => ['1-2', '2-1', 'r',  'above', 'bend right=15,tail,Leftarrow'],
  s => ['2-1', '1-2', 'UR', 'above', 'shift left=2pt,twohead,Leftrightarrow'],
);
foreach my $label (sort keys %expected_edges) {
  ok($edges{$label}, "case 15 retains unexpanded label $label");
  next unless $edges{$label};
  is_deeply([
      map { $edges{$label}->getAttributeNS($CD_NS, $_) }
        qw(from to dir labelpos style)
    ], $expected_edges{$label}, "case 15 edge $label metadata"); }
my @capitalized = $tikzcd_xc->findnodes(
  '//ltx:XMTok[@name="Rightarrow" or @name="Leftarrow" or @name="Leftrightarrow"]');
is_deeply([sort map { $_->getAttribute('name') } @capitalized],
  [qw(Leftarrow Leftrightarrow Rightarrow)], 'case 15 capitalized arrow styles survive parsing');
my @tikzcd_unparsed = $tikzcd_xc->findnodes(
  '//ltx:Math[contains(concat(" ", normalize-space(@class), " "), " ltx_math_unparsed ")]');
is(scalar(@tikzcd_unparsed), 0, 'case 15 every diagram cell parses');
assert_partition($tikzcd_xml, 'tikz-cd fixture');

my @ledgers = $routes_xc->findnodes('/ltx:document/capture:ledger');
is(scalar(@ledgers), 1, 'capture document has exactly one ledger');
my @ledger_children = grep { $_->nodeType == XML_ELEMENT_NODE } $ledgers[0]->childNodes;
is_deeply([map { $_->localname } @ledger_children], [qw(engine packages math encoding messages)],
  'ledger has exactly the five ordered contract children');
is($routes_xml->documentElement->lastChild->localname, 'ledger', 'ledger is the final document child');

# Parser-not-run is distinct from a successful parser with zero failed cells.
my ($noparse) = convert_document('literal:$n=p$', nomathparse => 1);
my ($noparse_ledger) = xpath($noparse->getDocument)->findnodes(
  '/ltx:document/capture:ledger/capture:math');
is($noparse_ledger->getAttribute('parser'), 'not-run', 'noparse records parser=not-run');
ok(!$noparse_ledger->hasAttribute('failedCells'), 'noparse omits failedCells');

# Capture-off remains a deterministic raw serialization and has no capture surface.
my ($capture_off) = convert_document(File::Spec->catfile($FIXTURES, 'capture-off.tex'), capture => 0);
my $capture_off_raw = $capture_off->toString(1);
is(sha256_hex(encode('UTF-8', $capture_off_raw)), $CAPTURE_OFF_SHA256,
  'capture-off representative raw serialization matches its checked-in SHA-256');
unlike($capture_off_raw, qr{http://dlmf\.nist\.gov/LaTeXML/capture}, 'capture-off has no capture namespace');
unlike($capture_off_raw, qr{capture:ledger}, 'capture-off has no ledger');

validate_capture_document($crlf, 'capture-crlf');
validate_capture_document($routes, 'capture-routes');
validate_capture_document($tikzcd, 'capture-tikzcd');

# Missing provenance occupies a slot.  Engine-generated token streams must
# obey the same delimiter/keyword matching rules as source-backed streams.
$positions_core->withState(sub {
    my ($state) = @_;
    my $gullet = $state->getStomach->getGullet;
    $gullet->readingFromMouth(Tokens(), sub {
        $gullet->unreadWithOccurrences([undef, { sourceId => 'sentinel', byteStart => 7 }, undef],
          T_OTHER('['), T_LETTER('x'), T_OTHER(']'));
        is(scalar(@{ $gullet->{pushback_occurrences} }), 3,
          'unlocated tokens retain occurrence slots beside located tokens');
        ok($gullet->readMatch(T_OTHER('('), T_OTHER('[')),
          'capture readMatch can backtrack and match an unlocated delimiter');
        is($gullet->readToken->toString, 'x', 'failed match preserves the next token');
        is($gullet->getCurrentOccurrence->{byteStart}, 7, 'failed match preserves occurrence alignment');
        ok($gullet->readMatch(T_OTHER(']')), 'unlocated closing delimiter matches');
        $gullet->unreadWithOccurrence(undef, Tokens(T_LETTER('p'), T_LETTER('t')));
        is($gullet->readKeyword('px', 'pt'), 'pt', 'capture keyword matching survives absent occurrences');
        return; });
    return; });

# Reduced from the interval paper's llncs front matter. Before the fix its
# affiliation text was consumed as part of an internal attribute name.
my $frontmatter_path = File::Spec->catfile($TEMP, 'frontmatter.xml');
my ($frontmatter_status, $frontmatter_messages) = run_command($^X, '-I', File::Spec->catdir($ROOT, 'lib'),
  File::Spec->catfile($ROOT, 'tools', 'dev', 'capture-fixture.pl'),
  File::Spec->catfile($FIXTURES, 'frontmatter.tex'), $frontmatter_path);
is($frontmatter_status, 0, 'capture front matter converts without errors or warnings') or diag($frontmatter_messages);
my $frontmatter_xml = XML::LibXML->load_xml(location => $frontmatter_path);
my $frontmatter_xc = xpath($frontmatter_xml);
is($frontmatter_xc->findvalue('string(//ltx:personname)'), 'First Author', 'front matter preserves the author');
like($frontmatter_xc->findvalue('string(//ltx:contact)'), qr/First university/,
  'front matter preserves the affiliation');
foreach my $math ($frontmatter_xc->findnodes('//ltx:Math')) {
  assert_source_bytes($frontmatter_xml, $math, 'front-matter fixture math');
  assert_owns_slice($frontmatter_xml, $math, '\[a=b\]', 'front-matter body display'); }
assert_partition($frontmatter_xml, 'front-matter fixture');
my $frontmatter_golden = XML::LibXML->load_xml(location => File::Spec->catfile($FIXTURES, 'frontmatter.xml'));
is(normalized_capture_xml($frontmatter_xml), normalized_capture_xml($frontmatter_golden),
  'front-matter capture golden matches after base and revision normalization only');
validate_capture_document($frontmatter_xml, 'capture-frontmatter');

# The preamble switch takes no argument; in particular it must not swallow
# the following documentclass or the first document token.
my $raw_input_path = File::Spec->catfile($TEMP, 'raw-input.xml');
my ($raw_input_status, $raw_input_messages) = run_command($^X, '-I', File::Spec->catdir($ROOT, 'lib'),
  File::Spec->catfile($ROOT, 'tools', 'dev', 'capture-fixture.pl'),
  File::Spec->catfile($FIXTURES, 'raw-input.tex'), $raw_input_path);
is($raw_input_status, 0, 'UseRawInputEncoding converts without errors or warnings') or diag($raw_input_messages);
my $raw_input_xml = XML::LibXML->load_xml(location => $raw_input_path);
like(xpath($raw_input_xml)->findvalue('string(//ltx:p)'),
  qr/^The first token after the command is retained\./, 'UseRawInputEncoding consumes no following input');
my ($raw_input_off) = convert_document(File::Spec->catfile($FIXTURES, 'raw-input.tex'), capture => 0);
like(xpath($raw_input_off->getDocument)->findvalue('string(//ltx:p)'),
  qr/^The first token after the command is retained\./, 'UseRawInputEncoding also consumes no input with capture off');
foreach my $math (xpath($raw_input_xml)->findnodes('//ltx:Math')) {
  assert_source_bytes($raw_input_xml, $math, 'raw-input fixture math'); }
assert_partition($raw_input_xml, 'raw-input fixture');

for my $flags (['--autoload'], ['--autoload', '--no-capture']) {
  my $auto_xml = fixture_document('raw-input', @$flags);
  like(xpath($auto_xml)->findvalue('string(//ltx:p)'), qr/^The first token after the command is retained\./,
    "UseRawInputEncoding autoloads LaTeX before documentclass (@$flags)");
  is(xpath($auto_xml)->findvalue('count(//ltx:ERROR)'), 0, 'autoload emits no undefined-command residue'); }

my $label_path = File::Spec->catfile($TEMP, 'label-values.xml');
my ($label_status, $label_messages) = run_command($^X, '-I', File::Spec->catdir($ROOT, 'lib'),
  File::Spec->catfile($ROOT, 'tools', 'dev', 'capture-fixture.pl'),
  File::Spec->catfile($FIXTURES, 'label-values.tex'), $label_path);
is($label_status, 0, 'label-value fixture converts without errors or warnings') or diag($label_messages);
my $label_xml = XML::LibXML->load_xml(location => $label_path);
my @labeled_items = xpath($label_xml)->findnodes('//ltx:item');
is_deeply(JSON::PP->new->decode(cattr($labeled_items[0], 'labelValues')), { 'LABEL:plain' => '1' },
  'plain optional item records currentlabel, not its visible Case D text');
is_deeply(JSON::PP->new->decode(cattr($labeled_items[1], 'labelValues')),
  { 'LABEL:custom' => 'A', 'LABEL:zero' => '0', 'LABEL:second' => 'second' },
  'one target retains each label-time value, including zero');
my $label_before = $label_xml->toString;
for my $strategy (qw(deferred indexed)) {
  my $projection = LaTeXAI::Post::Markdown->new(toc => 0)->project($label_xml, strategy => $strategy);
  like($projection->{markdown}, qr/Case A/, "$strategy resolves the custom counter in a heading");
  like($projection->{markdown}, qr/1; A; 0; second\./, "$strategy resolves distinct labels on shared targets"); }
is($label_xml->toString, $label_before, 'label projection leaves the capture IR unchanged');
validate_capture_document($label_xml, 'capture-label-values');

my $alphabet_xml = fixture_document('math-alphabets');
my $alphabet_xc = xpath($alphabet_xml);
for my $case (
  ['R', ['\\mathbb', '\\mathbb']], ['L', ['\\mathbf', '\\mathcal']],
  ['g', ['\\mathfrak']], ['T', ['\\mathsf']], ['x', ['\\mathit']],
  ['v', ['\\boldsymbol']], ['w', ['\\bm']], ['a', ['\\mathbf']], ['b', ['\\mathbf']]) {
  my ($value, $stack) = @$case;
  my ($token) = $alphabet_xc->findnodes('//ltx:XMTok[text()="' . $value . '"]');
  is_deeply(JSON::PP->new->decode(cattr($token, 'mathAlphabets')), [$stack],
    "requested alphabet stack survives on $value"); }
my ($alpha) = $alphabet_xc->findnodes('//ltx:XMTok[@name="alpha"]');
is_deeply(JSON::PP->new->decode(cattr($alpha, 'mathAlphabets')), [['\\mathbf']],
  'primitive math symbols retain the request even when their resolved font ignores it');
my @tr = $alphabet_xc->findnodes('//ltx:XMTok[text()="tr"]');
is_deeply(JSON::PP->new->decode(cattr($tr[0], 'mathAlphabets')), [['\\mathrm']],
  'multi-letter default upright font still records the explicit request');
is_deeply(JSON::PP->new->decode(cattr($tr[1], 'mathAlphabets')), [['\\mathrm'], []],
  'ligature preserves distinct explicit and unmarked source runs');
is($alphabet_xc->findvalue('count(//ltx:text[@capture:mathAlphabets] | //ltx:XMTok[text()="z" or text()="q"][@capture:mathAlphabets])'), 0,
  'alphabet requests stop at text mode and do not leak into later or nested math');
is(without_capture($alphabet_xml), without_capture(fixture_document('math-alphabets', '--no-capture')),
  'alphabet metadata leaves the complete ltx tree unchanged');
assert_partition($alphabet_xml, 'math-alphabet fixture');
validate_capture_document($alphabet_xml, 'capture-math-alphabets');

my $juxtaposition_xml = fixture_document('juxtaposition');
my $juxtaposition_xc = xpath($juxtaposition_xml);
my @formulas = $juxtaposition_xc->findnodes('//ltx:Math');
my @decisions;
for my $index (0 .. $#formulas) {
  my @apps = xpath($formulas[$index])->findnodes('.//ltx:XMApp[@capture:juxtaposition]');
  push @decisions, [map { @{ JSON::PP->new->decode(cattr($_, 'juxtaposition')) } } @apps]; }
is($decisions[0][0]{decision}, 'application', 'declared operator is recorded as application');
is($decisions[0][0]{evidence}{leftRole}, 'OPFUNCTION', 'declared operator records its known role');
is($decisions[0][0]{rule}, 'addEasyArgs', 'declared operator records the deciding grammar rule');
is($decisions[1][0]{decision}, 'product', 'undeclared f(x) retains the engine product reading');
is($decisions[1][0]{evidence}{leftRole}, 'UNKNOWN', 'undeclared f records the absence of a function role');
is($decisions[1][0]{evidence}{rightShape}, 'ltx:XMDual', 'f(x) retains the delimited right-hand shape');
is($decisions[2][0]{decision}, 'product', 'cT records implicit multiplication');
is($decisions[2][0]{evidence}{rightRole}, 'UNKNOWN', 'cT records the right identifier role');
is($decisions[2][0]{evidence}{rightShape}, 'ltx:XMTok', 'cT differs from the delimited f(x) evidence');
is(scalar(@{ $decisions[3] }), 2, 'flattening abc preserves both adjacency decisions');
is(scalar(@{ $decisions[4] }), 0, 'explicit multiplication is not marked as a juxtaposition guess');
is(scalar(@{ $decisions[5] }), 0, 'a declared operator without an argument has no application decision');
is($decisions[6][0]{rule}, 'addTrigFunArgs', 'bare trig argument records its actual grammar rule');
ok($decisions[7][0]{evidence}{explicitApply}, 'explicit application records its APPLYOP evidence');
is($decisions[7][0]{rule}, 'requireArgs', 'explicit application records requireArgs');
is(without_capture($juxtaposition_xml), without_capture(fixture_document('juxtaposition', '--no-capture')),
  'juxtaposition evidence leaves the complete ltx tree unchanged');
my $juxtaposition_noparse = fixture_document('juxtaposition', '--noparse');
is(xpath($juxtaposition_noparse)->findvalue('count(//*[@capture:juxtaposition])'), 0,
  'no parser means no parser decision markers');
foreach my $math (@formulas) { assert_source_bytes($juxtaposition_xml, $math, 'juxtaposition fixture math'); }
assert_partition($juxtaposition_xml, 'juxtaposition fixture');
validate_capture_document($juxtaposition_xml, 'capture-juxtaposition');

# Deferred title math is re-digested at \maketitle; the recorded slice must
# still be the author's $x=y$, not the callsite. Body display stays put.
my $deferred_path = File::Spec->catfile($TEMP, 'deferred-title.xml');
my ($deferred_status, $deferred_messages) = run_command($^X, '-I', File::Spec->catdir($ROOT, 'lib'),
  File::Spec->catfile($ROOT, 'tools', 'dev', 'capture-fixture.pl'),
  File::Spec->catfile($FIXTURES, 'deferred-title.tex'), $deferred_path);
is($deferred_status, 0, 'deferred-title converts without errors or warnings') or diag($deferred_messages);
my $deferred_xml = XML::LibXML->load_xml(location => $deferred_path);
my $deferred_xc = xpath($deferred_xml);
my ($deferred_title) = $deferred_xc->findnodes('//ltx:title//ltx:Math');
my ($deferred_body)  = $deferred_xc->findnodes('//ltx:equation//ltx:Math');
ok($deferred_title, 'deferred-title has title math');
ok($deferred_body,  'deferred-title has body display math');
is(0 + cattr($deferred_title, 'byteStart'), 40, 'deferred-title title byteStart');
is(0 + cattr($deferred_title, 'byteEnd'),   45, 'deferred-title title byteEnd');
is(0 + cattr($deferred_title, 'fromLine'),   2, 'deferred-title title fromLine');
is(0 + cattr($deferred_title, 'fromCol'),   19, 'deferred-title title fromCol');
is(0 + cattr($deferred_title, 'toCol'),     23, 'deferred-title title toCol');
is(cattr($deferred_title, 'provenance'), 'source', 'deferred-title title provenance');
assert_owns_slice($deferred_xml, $deferred_title, '$x=y$', 'deferred-title title math');
assert_source_bytes($deferred_xml, $deferred_title, 'deferred-title title math');
is(0 + cattr($deferred_body, 'byteStart'), 144, 'deferred-title body byteStart');
is(0 + cattr($deferred_body, 'byteEnd'),   151, 'deferred-title body byteEnd');
assert_owns_slice($deferred_xml, $deferred_body, '\[a=b\]', 'deferred-title body display');
assert_source_bytes($deferred_xml, $deferred_body, 'deferred-title body display');
assert_partition($deferred_xml, 'deferred-title fixture');
my $deferred_golden = XML::LibXML->load_xml(location => File::Spec->catfile($FIXTURES, 'deferred-title.xml'));
is(normalized_capture_xml($deferred_xml), normalized_capture_xml($deferred_golden),
  'deferred-title capture golden matches after base and revision normalization only');
validate_capture_document($deferred_xml, 'capture-deferred-title');

# Nested text-mode math inside an alphabet command must keep its own dollars.
# cleanup_Math unwraps the outer Math when it is only XMText (upstream);
# the remaining carrier is the inner $z$.
my $nested_path = File::Spec->catfile($TEMP, 'nested-text.xml');
my ($nested_status, $nested_messages) = run_command($^X, '-I', File::Spec->catdir($ROOT, 'lib'),
  File::Spec->catfile($ROOT, 'tools', 'dev', 'capture-fixture.pl'),
  File::Spec->catfile($FIXTURES, 'nested-text.tex'), $nested_path);
is($nested_status, 0, 'nested-text converts without errors or warnings') or diag($nested_messages);
my $nested_xml = XML::LibXML->load_xml(location => $nested_path);
my $nested_xc = xpath($nested_xml);
my @nested_math = $nested_xc->findnodes('//ltx:Math');
is(scalar(@nested_math), 1, 'nested-text keeps the inner math carrier after cleanup_Math unwrap');
my $nested_inner = $nested_math[0];
is(0 + cattr($nested_inner, 'byteStart'), 83, 'nested-text inner byteStart');
is(0 + cattr($nested_inner, 'byteEnd'),   86, 'nested-text inner byteEnd');
is(0 + cattr($nested_inner, 'fromLine'),   4, 'nested-text inner fromLine');
is(0 + cattr($nested_inner, 'fromCol'),   22, 'nested-text inner fromCol');
is(0 + cattr($nested_inner, 'toCol'),     24, 'nested-text inner toCol');
is(cattr($nested_inner, 'provenance'), 'source', 'nested-text inner provenance');
assert_owns_slice($nested_xml, $nested_inner, '$z$', 'nested-text inner math');
assert_source_bytes($nested_xml, $nested_inner, 'nested-text inner math');
my ($nested_z) = $nested_xc->findnodes('//ltx:XMTok[text()="z"]');
ok($nested_z, 'nested-text has the inner z token');
ok(!$nested_z->hasAttributeNS($CAPTURE_NS, 'mathAlphabets'),
  'inner XMTok carries no math alphabet request from text-mode math');
assert_partition($nested_xml, 'nested-text fixture');
my $nested_golden = XML::LibXML->load_xml(location => File::Spec->catfile($FIXTURES, 'nested-text.xml'));
is(normalized_capture_xml($nested_xml), normalized_capture_xml($nested_golden),
  'nested-text capture golden matches after base and revision normalization only');
validate_capture_document($nested_xml, 'capture-nested-text');

# Citation keys are Semiverbatim; re-invocation must keep the parameter
# type's braces so \@@bibref does not swallow one token and spill the rest.
my $cite_path = File::Spec->catfile($TEMP, 'cite.xml');
my ($cite_status, $cite_messages) = run_command($^X, '-I', File::Spec->catdir($ROOT, 'lib'),
  File::Spec->catfile($ROOT, 'tools', 'dev', 'capture-fixture.pl'),
  File::Spec->catfile($FIXTURES, 'cite.tex'), $cite_path);
is($cite_status, 0, 'cite converts without errors or warnings') or diag($cite_messages);
my $cite_xml = XML::LibXML->load_xml(location => $cite_path);
my $cite_xc = xpath($cite_xml);
my @cite_bibrefs = $cite_xc->findnodes('//ltx:bibref');
ok(scalar(@cite_bibrefs) >= 1, 'cite fixture emits bibref elements');
is($cite_bibrefs[0]->getAttribute('bibrefs'), 'key_one,key_two',
  'first bibref carries both citation keys');
is($cite_xc->findvalue('count(//ltx:bibref/text()[normalize-space()])'), 0,
  'no bibref has a text child');
is(without_capture($cite_xml), without_capture(fixture_document('cite', '--no-capture')),
  'cite capture metadata leaves the complete ltx tree unchanged');
assert_partition($cite_xml, 'cite fixture');
my $cite_golden = XML::LibXML->load_xml(location => File::Spec->catfile($FIXTURES, 'cite.xml'));
is(normalized_capture_xml($cite_xml), normalized_capture_xml($cite_golden),
  'cite capture golden matches after base and revision normalization only');
validate_capture_document($cite_xml, 'capture-cite');

done_testing();

#**********************************************************************
1;
