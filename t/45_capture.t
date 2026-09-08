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
  assert_source_bytes($frontmatter_xml, $math, 'front-matter fixture math'); }
assert_partition($frontmatter_xml, 'front-matter fixture');
my $frontmatter_golden = XML::LibXML->load_xml(location => File::Spec->catfile($FIXTURES, 'frontmatter.xml'));
is(normalized_capture_xml($frontmatter_xml), normalized_capture_xml($frontmatter_golden),
  'front-matter capture golden matches after base and revision normalization only');
validate_capture_document($frontmatter_xml, 'capture-frontmatter');

done_testing();

#**********************************************************************
1;
