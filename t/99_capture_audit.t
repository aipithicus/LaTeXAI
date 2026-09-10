use strict;
use warnings;
use Test::More;
use FindBin;
use File::Spec;
use File::Path qw(make_path);
use File::Temp qw(tempdir);
use Cwd qw(abs_path);
use Encode qw(encode);
use IPC::Run3;
use XML::LibXML;
use lib File::Spec->catdir($FindBin::Bin, '..', 'tools', 'dev');
use CaptureAudit qw(read_json write_json read_raw write_raw run_conversion
  json_bytes object_hash finish_run tree_hashes);
use CaptureStrip qw(without_capture);

chdir File::Spec->catdir($FindBin::Bin, '..') or die $!;
my $temp = tempdir('capture-audit-XXXXXX', DIR => 'temp/t', CLEANUP => 1);
$temp = abs_path($temp);
my %defaults = (preload => [], searchpaths => [], includecomments => 0,
  includepathpis => 0, verbosity => -2);
my $counter = 0;
sub convert {
  my ($source, $options) = @_;
  my $result = run_conversion({ texpath => $source, options => $options }, "$temp/helper-" . ++$counter);
  ok(!$result->{failure}, 'fresh-process conversion succeeds') or diag(json_bytes($result));
  return $result; }
sub xml { return XML::LibXML->new(load_ext_dtd => 0)->load_xml(string => $_[0]); }

my $ns = 'http://dlmf.nist.gov/LaTeXML';
my $capture = 'http://dlmf.nist.gov/LaTeXML/capture';
my $off = xml(qq{<document xmlns="$ns"><p><text>a</text> <text>b</text></p></document>});
my $on = xml(qq{<document xmlns="$ns" xmlns:capture="$capture" capture:source="x"><p><text>a</text> <text>b</text></p><capture:ledger/></document>});
is(without_capture($on), without_capture($off), 'only capture metadata is stripped');
my $raw_off = $off->toString;
my $raw_on = $on->toString;
without_capture($on);
is($on->toString, $raw_on, 'stripping leaves its input untouched');
my $no_space = xml(qq{<document xmlns="$ns"><p><text>a</text><text>b</text></p></document>});
isnt(without_capture($off), without_capture($no_space), 'inter-element prose space remains observable');
for my $tag ('text', 'verbatim') {
  isnt(without_capture(xml(qq{<document xmlns="$ns"><$tag> </$tag></document>})),
    without_capture(xml(qq{<document xmlns="$ns"><$tag></$tag></document>})), "$tag whitespace-only content survives"); }
like(without_capture(xml(qq{<document xmlns="$ns"><!--witness--><p>\x{3b1}</p></document>})),
  qr/<!--witness-->.*\x{3b1}/, 'comments and Unicode survive canonicalization');
is($off->toString, $raw_off, 'all strip checks preserve off DOM');
XML::LibXML->new(no_blanks => 1)->load_xml(string => '<root><child/></root>');
isnt(without_capture($off), without_capture($no_space), 'another parser cannot silently disable audit whitespace');

my %custom = (%defaults, preload => ['LaTeX.pool', 'auditoption.sty'],
  searchpaths => [abs_path('t/capture-audit/support')], nomathparse => 1);
my $custom_off = convert('t/capture-audit/options.tex', { %custom, capture => 0 });
my $custom_on = convert('t/capture-audit/options.tex', { %custom, capture => 1 });
like($custom_on->{raw}, qr/AUDITOPTION/, 'non-default search path and preload affect child output');
is($custom_on->{status_code}, 0, 'custom preload resolves without engine errors');
is_deeply($custom_on->{options}, { %custom, capture => 1 }, 'all nested options cross the boundary intact');
is($custom_off->{stripped}, $custom_on->{stripped}, 'non-default pair differs only in capture');
my $parsed = convert('t/capture-audit/options.tex', { %custom, nomathparse => 0, capture => 1 });
isnt($parsed->{stripped}, $custom_on->{stripped}, 'non-default parsing option has an observable effect');

my $missing = convert('t/capture-audit/options.tex', { %defaults, capture => 0 });
cmp_ok($missing->{status_code}, '>=', 2, 'engine diagnostic is independent of document/process success');
my $failed = run_conversion({ texpath => "$temp/absent.tex", options => \%defaults }, "$temp/missing");
is($failed->{failure}, 'conversion', 'no document is a conversion failure');
for my $case (
  ['process', 'use CaptureAudit qw(read_json write_json); my $r=read_json($ARGV[0]); write_json($ARGV[1], {format=>$CaptureAudit::FORMAT,options=>$r->{options},ok=>1}); exit 7;', 'helper-process'],
  ['json', 'open my $f, q(>), $ARGV[1]; print {$f} q(not json); close $f;', 'helper-protocol'],
  ['absent', 'exit 0;', 'helper-protocol']) {
  my ($name, $program, $expected) = @$case;
  write_raw("$temp/$name.pl", $program);
  my $result = run_conversion({ texpath => 'unused', options => {} }, "$temp/bad-$name", "$temp/$name.pl");
  is($result->{failure}, $expected, "$name helper failure cannot become an IR residual"); }

# The real Util::Test golden comparison stays green under every capture-only
# mutation. The fixture's expected off marker is asserted before its temporary
# reference is used to exercise the test harness, not to bless an engine golden.
local $ENV{LATEXAI_AUDIT_TEST_RESIDUAL} = 'known';
my $reference = convert('t/capture-audit/residual.tex', { %defaults, capture => 0 });
like($reference->{raw}, qr/>stable</, 'controlled fixture has the specified off reading');
write_raw("$temp/reference.xml", encode('UTF-8', $reference->{raw}));
my $driver = "$temp/v1-driver.t";
sub driver_text {
  my (@sources) = @_;
  return "use LaTeXML::Util::Test; use LaTeXML::Core;\n" . join('', map {
      "latexml_ok('$_', '$temp/reference.xml', '$_');\n"
    } @sources) . "done_testing();\n"; }
write_raw($driver, driver_text('t/capture-audit/residual.tex'));
sub prove_driver {
  my ($name, $baseline, $residual, $plain) = @_;
  my $out = "$temp/$name";
  make_path($out);
  local $ENV{LATEXAI_AUDIT_OUTPUT} = $out;
  local $ENV{LATEXAI_AUDIT_BASELINE} = $baseline;
  local $ENV{LATEXAI_AUDIT_LEGACY_OFF};
  local $ENV{LATEXAI_AUDIT_TEST_RESIDUAL} = $residual;
  my ($stdout, $stderr);
  my @command = ($^X, '-I', 'lib', '-I', 'tools/dev');
  push @command, '-MCaptureOffAudit' unless $plain;
  push @command, $driver;
  run3(\@command, undef, \$stdout, \$stderr);
  my $status = $?;
  write_raw("$out/stdout.txt", $stdout);
  write_raw("$out/stderr.txt", $stderr);
  my $report = !$plain && -f "$out/v1-driver.t/report.json" ? read_json("$out/v1-driver.t/report.json") : undef;
  return ($status, $report, $out, $stdout . $stderr); }
my ($base_status, $base_report, $base_dir, $base_log) = prove_driver('known', undef, 'known');
is($base_status, 0, 'explicit record permits a known residual') or diag($base_log);
my @keys = keys %{ $base_report->{cases} };
is(scalar @keys, 1, 'one controlled fixture recorded');
ok($base_report->{cases}{$keys[0]}{different}, 'known residual is explicitly present');
my $baseline_hash = object_hash(tree_hashes($base_dir));
my ($same_status, $same_report, $same_dir, $same_log) = prove_driver('same', $base_dir, 'known');
is($same_status, 0, 'unchanged known residual passes') or diag($same_log);
my ($changed_status, $changed_report) = prove_driver('changed', $base_dir, 'changed');
isnt($changed_status, 0, 'changed residual fails without changing the failing fixture count');
is_deeply([sort keys %{ $changed_report->{cases} }], [sort @keys], 'changed residual retains the same fixture identity');
like(join(' ', @{ $changed_report->{issues} }), qr/changed-residual/, 'changed residual has a distinct disposition');
my ($plain_status) = prove_driver('ordinary', undef, 'changed', 1);
is($plain_status, 0, 'ordinary golden success cannot mask the preceding audit failure');
my ($removed_status, $removed_report) = prove_driver('removed', $base_dir, 'stable');
isnt($removed_status, 0, 'residual removal requires review');
like(join(' ', @{ $removed_report->{issues} }), qr/removed-residual/, 'removal is identified');
my ($clean_status, $clean_report, $clean_dir) = prove_driver('clean', undef, 'stable');
is($clean_status, 0, 'equal pair can establish a baseline');
my ($new_status, $new_report) = prove_driver('new-difference', $clean_dir, 'known');
isnt($new_status, 0, 'new capture difference fails');
like(join(' ', @{ $new_report->{issues} }), qr/new-residual/, 'new residual is identified');

{
  local $ENV{LATEXAI_AUDIT_TEST_OFF} = 'altered';
  my $altered = convert('t/capture-audit/residual.tex', { %defaults, capture => 0 });
  write_raw("$temp/reference.xml", encode('UTF-8', $altered->{raw}));
  my ($raw_status, $raw_report) = prove_driver('raw-change', $clean_dir, 'altered');
  isnt($raw_status, 0, 'raw capture-off drift fails even when off and on still agree');
  ok(!$raw_report->{cases}{$keys[0]}{different}, 'raw-byte gate does not depend on an off/on residual');
  like(join(' ', @{ $raw_report->{issues} }), qr/capture-off-bytes/, 'raw byte failure is independently identified');
}
write_raw("$temp/reference.xml", encode('UTF-8', $reference->{raw}));

write_raw($driver, "use Test::More; pass('driver still passes'); done_testing();\n");
my ($omitted_status, $omitted_report) = prove_driver('omitted', $base_dir, 'known');
isnt($omitted_status, 0, 'omitting a previously covered conversion fails');
like(join(' ', @{ $omitted_report->{issues} }), qr/omitted-fixture/, 'omission identifies missing fixture');
write_raw($driver, driver_text('t/capture-audit/residual.tex', 't/capture-audit/residual.tex'));
my ($added_status, $added_report) = prove_driver('added', $base_dir, 'known');
isnt($added_status, 0, 'additional conversion requires baseline coverage');
like(join(' ', @{ $added_report->{issues} }), qr/new-fixture/, 'addition is identified');
my ($repeated_case) = grep { $_->{ordinal} == 2 } values %{ $added_report->{cases} };
ok(!$repeated_case->{diagnostics_different}, 'fresh off/on controls exclude repeated-prove-process warnings');
ok(exists $repeated_case->{driver_diagnostics}, 'original driver diagnostics remain independent evidence');

# Exercise the non-default options through the actual observer, as well as the
# helper contract checked above. The ordinary golden is temporary harness data.
write_raw("$temp/options-reference.xml", encode('UTF-8', $custom_off->{raw}));
write_raw("$temp/options.json", json_bytes(\%custom));
write_raw($driver, "use LaTeXML::Util::Test; use LaTeXML::Core; use CaptureAudit qw(read_json);\n"
  . "latexml_ok('t/capture-audit/options.tex', '$temp/options-reference.xml', 'nondefault', undef, read_json('$temp/options.json')); done_testing();\n");
my ($option_status, $option_report, $option_dir, $option_log) = prove_driver('driver-options', undef, 'known');
is($option_status, 0, 'real driver options survive observer and subprocess') or diag($option_log);
my ($option_case) = values %{ $option_report->{cases} };
ok(!$option_case->{different}, 'non-default real-driver pair agrees after stripping');
is_deeply($option_case->{options}, \%custom, 'observer records the actual driver options');

make_path("$temp/skip-suite");
write_raw("$temp/skip-suite/absent-golden.tex", "\\relax\n");
write_raw($driver, "use LaTeXML::Util::Test; latexml_tests('$temp/skip-suite');\n");
my ($skip_status, $skip_report, $skip_dir, $skip_log) = prove_driver('skip', undef, 'known');
is($skip_status, 0, 'intentional missing-golden skip is recorded') or diag($skip_log);
is(scalar @{ $skip_report->{skips} }, 1, 'skip reason is explicit');
is(scalar keys %{ $skip_report->{cases} }, 0, 'skip is not counted as an audited conversion');
unlink "$temp/skip-suite/absent-golden.tex" or die $!;
my ($skip_changed_status, $skip_changed_report) = prove_driver('skip-changed', $skip_dir, 'known');
isnt($skip_changed_status, 0, 'removing a skipped source still changes coverage');
like(join(' ', @{ $skip_changed_report->{issues} }), qr/changed-fixture-inventory/, 'skipped-source omission is identified');

write_raw($driver, driver_text('t/capture-audit/nonexistent.tex'));
my ($failed_status, $failed_report) = prove_driver('failed-conversion', undef, 'known');
isnt($failed_status, 0, 'failed off conversion is reported and rejects the record');
like(join(' ', @{ $failed_report->{issues} }), qr/capture-off-conversion/, 'conversion failure has its own category');
is(object_hash(tree_hashes($base_dir)), $baseline_hash, 'all successful and failed comparisons leave baseline bytes unchanged');

my $state = { root => 'test', perl => {}, environment => {}, files => {} };
my $run = finish_run($base_dir, ['v1-driver.t'], undef, 0, $state, $state);
ok($run->{qualified}, 'completed ordinary and audit observations qualify a record');
my $missing_driver = finish_run($same_dir, ['v1-driver.t', 'absent.t'], $base_dir, 0, $state, $state);
ok(!$missing_driver->{qualified}, 'entire missing driver cannot escape per-driver checks');
like(join(' ', @{ $missing_driver->{issues} }), qr/missing-driver-report:absent.t/, 'missing driver is named');
my $failed_prove = finish_run($same_dir, ['v1-driver.t'], $base_dir, 1, $state, $state);
ok(!$failed_prove->{qualified}, 'ordinary suite failure prevents audit qualification');
my $drift = finish_run($same_dir, ['v1-driver.t'], $base_dir, 0, $state, { %$state, root => 'changed' });
like(join(' ', @{ $drift->{issues} }), qr/input-state-changed-during-run/, 'changing input state invalidates a run');
write_raw("$base_dir/v1-driver.t/$keys[0].on.xml", '<corrupted/>');
my $corrupt = finish_run($same_dir, ['v1-driver.t'], $base_dir, 0, $state, $state);
like(join(' ', @{ $corrupt->{issues} }), qr/artifact-integrity/, 'modified retained evidence cannot qualify a comparison');
done_testing();
