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
  json_bytes object_hash finish_run tree_hashes restrip_report compare_case
  review_case_issues file_hash);
use CaptureStrip qw(without_capture);
use CaptureRuntime qw(canonical_path runtime_contract project_searchpaths);
use MIME::Base64 qw(encode_base64);

chdir File::Spec->catdir($FindBin::Bin, '..') or die $!;
{
  my $files = tree_hashes('scripts');
  ok(!exists $files->{'scripts/local.psd1'}, 'ignored local config is not snapshotted');
  ok(exists $files->{'scripts/latexai-common.ps1'}, 'tracked scripts are snapshotted');
}
my $temp = tempdir('capture-audit-XXXXXX', DIR => 'temp/t', CLEANUP => 1);
$temp = abs_path($temp);
my %defaults = (preload => [], searchpaths => [], includecomments => 0,
  includepathpis => 0, verbosity => -2);
my $counter = 0;
local $ENV{LATEXAI_AUDIT_PROJECT_BASELINE};
# Nested under capture-audit.pl compare --transitions, the outer env would
# otherwise fail dummy finish_run baselines as transition-baseline.
local $ENV{LATEXAI_AUDIT_TRANSITIONS};
sub convert {
  my ($source, $options) = @_;
  my $result = run_conversion({ texpath => $source, options => $options }, "$temp/helper-" . ++$counter);
  ok(!$result->{failure}, 'fresh-process conversion succeeds') or diag(json_bytes($result));
  return $result; }
sub xml { return XML::LibXML->new(load_ext_dtd => 0, no_blanks => 0)->load_xml(string => $_[0]); }

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
for my $root ('ltx:custom', 'foreign:document', 'document') {
  my $namespaces = qq{xmlns:ltx="$ns" xmlns:foreign="urn:audit:foreign" xmlns:c="$capture"};
  my $body = '<!--witness--><ltx:text>a</ltx:text> <ltx:text>b</ltx:text>'
    . '<foreign:ledger revision="manuscript"/>';
  my $plain = xml(qq{<$root $namespaces>$body</$root>});
  my $captured = xml(qq{<$root $namespaces c:source="author">$body<c:ledger><c:engine revision="old"/></c:ledger></$root>});
  my $original = $captured->toString;
  is(without_capture($captured), without_capture($plain), "$root ledger stripped by namespace under the actual root");
  is($captured->toString, $original, "$root input stays unchanged");
  my $changed = xml(qq{<$root $namespaces>$body<ltx:text>changed</ltx:text></$root>});
  isnt(without_capture($captured), without_capture($changed), "$root manuscript change stays observable");
  like(without_capture($captured), qr/foreign:ledger revision="manuscript"/, "$root foreign ledger survives");
}
{
  my $plain = xml(qq{<document xmlns="$ns" xmlns:c="$capture"><bibliography/>\n</document>});
  my $pretty = xml(qq{<document xmlns="$ns" xmlns:c="$capture"><bibliography/>\n  <c:ledger><c:math total="0"/></c:ledger>\n</document>});
  is(without_capture($pretty), without_capture($plain), 'pretty-printed ledger indent is not manuscript text');
}
XML::LibXML->new(no_blanks => 1)->load_xml(string => '<root><child/></root>');
isnt(without_capture($off), without_capture($no_space), 'another parser cannot silently disable audit whitespace');

{
  my $root = "$temp/runtime";
  make_path("$root/old", "$root/new");
  my $launcher = "\@echo off\nif \"%PERL_ROOT%\"==\"\" (\n  echo kpsewhich: missing PERL_ROOT 1>&2\n  exit /b 1\n)\n"
    . '"%PERL_ROOT%\perl\bin\perl.exe" "%~dp0..\helper.pl" %*' . "\n";
  write_raw("$root/old/wrapper.cmd", $launcher);
  write_raw("$root/new/wrapper.cmd", $launcher);
  write_raw("$root/helper.pl", '1;');
  my $files = { map { $_ => file_hash("$root/$_") } qw(old/wrapper.cmd new/wrapper.cmd helper.pl) };
  my $old = { root => $root, files => $files, environment => {
      PERL_ROOT => 'C:\portable\perl', LATEXML_KPSEWHICH => "$root/old/wrapper.cmd",
      LATEXAI_AUDIT_JOBS => 2, LATEXML_KPSEWHICH_CACHE_ONLY => 1 } };
  my $new = { %$old, environment => { %{$old->{environment}}, PERL_ROOT => 'C:/portable/perl',
      LATEXML_KPSEWHICH => "$root/new/wrapper.cmd", LATEXAI_AUDIT_JOBS => 10 } };
  my ($a, $b) = (runtime_contract($old), runtime_contract($new));
  is_deeply($a->{identity}, $b->{identity}, 'verified launcher relocation and path spelling preserve runtime meaning');
  isnt($a->{evidence}{kpsewhich}{launcher}, $b->{evidence}{kpsewhich}{launcher}, 'physical launcher addresses remain evidence');
  is($a->{execution}{workers}, 2, 'historical worker count stays recorded');
  is($b->{execution}{workers}, 10, 'new worker count stays recorded');
  is(canonical_path('D:\engine\scripts\..\tools\helper.pl'), 'D:/engine/tools/helper.pl', 'relative wrapper target resolves lexically');
  isnt(canonical_path('D:/Case'), canonical_path('D:/case'), 'filename case is not silently folded');
  for my $change ([LATEXML_KPSEWHICH_CACHE_ONLY => 0], [PERL5OPT => '-MChanged'], [PERL_ROOT => 'C:/other/perl']) {
    my $changed = { %$new, environment => { %{$new->{environment}}, @$change } };
    isnt(object_hash(runtime_contract($changed)->{identity}), object_hash($a->{identity}), "$change->[0] semantic drift fails equivalence");
  }
  # Historical source must be hash-verified, even if its old address no longer exists.
  $old->{uncommitted_files_base64}{'old/wrapper.cmd'} = encode_base64($launcher, '');
  unlink "$root/old/wrapper.cmd" or die $!;
  is_deeply(runtime_contract($old)->{identity}, $a->{identity}, 'retained source proves a removed historical launcher');
  $old->{uncommitted_files_base64}{'old/wrapper.cmd'} = encode_base64('tampered', '');
  ok(!eval { runtime_contract($old); 1 }, 'unverified historical launcher fails closed');
  for my $changed ($launcher . "echo extra\n", $launcher =~ s/ %\*/ --extra %*/r) {
    write_raw("$root/new/wrapper.cmd", $changed);
    my $state = { %$new, files => { %$files, 'new/wrapper.cmd' => file_hash("$root/new/wrapper.cmd") } };
    isnt(object_hash(runtime_contract($state)->{identity}), object_hash($b->{identity}), 'extra wrapper behavior is not a relocation');
  }
  write_raw("$root/other.pl", '1;');
  write_raw("$root/new/wrapper.cmd", $launcher =~ s/helper\.pl/other.pl/r);
  my $changed_target = { %$new, files => { %$files, 'new/wrapper.cmd' => file_hash("$root/new/wrapper.cmd"),
      'other.pl' => file_hash("$root/other.pl") } };
  isnt(object_hash(runtime_contract($changed_target)->{identity}), object_hash($b->{identity}), 'different resolved helper is not a relocation');
}
{
  my $engine = "$temp/engine";
  my $article = "$temp/article";
  my $source = "$article/p-tex";
  my @receipts;
  my @documents;
  for my $variant (qw(old new)) {
    my $support = "$engine/" . ($variant eq 'old' ? 'private/scripts' : 'scripts/preloads');
    my $job = "$temp/$variant-job";
    push @receipts, { article => { directory => $article, slug => 'p' }, details => { perl => 'C:/perl.exe',
        arguments => ['-I', "$engine/lib", "$engine/bin/latexml", '--capture', "--path=$source", "--path=$support",
          '--preload=gauntlet.sty', "--log=$job/p.log", "--destination=$job/p.xml",
          ($variant eq 'old' ? "$source/p.tex" : 'p.tex')] } };
    push @documents, xml(qq{<?latexml searchpaths="$support,$source"?><document xmlns="$ns"><p>a b</p><!--keep--></document>});
  }
  my $raw = $documents[0]->toString;
  my $a = project_searchpaths($documents[0], $receipts[0], "$temp/old-job");
  my $b = project_searchpaths($documents[1], $receipts[1], "$temp/new-job");
  is_deeply($a->{identity}, $b->{identity}, 'recorded invocation proves preload relocation and source cwd equivalence');
  is(without_capture($a->{document}), without_capture($b->{document}), 'only verified runtime metadata projects to logical roles');
  is($documents[0]->toString, $raw, 'metadata projection preserves original XML');
  my $changed_doc = $documents[1]->cloneNode(1);
  ($changed_doc->findnodes('//*[local-name()="p"]'))[0]->appendText(' changed');
  isnt(without_capture(project_searchpaths($changed_doc, $receipts[1], "$temp/new-job")->{document}),
    without_capture($a->{document}), 'real manuscript drift survives runtime projection');
  my $changed = read_json_after_clone($receipts[1]);
  $changed->{details}{arguments}[3] = '--noparse';
  isnt(object_hash(project_searchpaths($documents[1], $changed, "$temp/new-job")->{identity}),
    object_hash($a->{identity}), 'changed compiler options stay observable');
  my $lie = xml(qq{<?latexml searchpaths="elsewhere,$source"?><document/>});
  ok(!eval { project_searchpaths($lie, $receipts[1], "$temp/new-job"); 1 }, 'PI not backed by invocation fails');
  my $duplicate = xml(qq{<?latexml searchpaths="$engine/scripts/preloads,$source"?><?latexml searchpaths="$engine/scripts/preloads,$source"?><document/>});
  ok(!eval { project_searchpaths($duplicate, $receipts[1], "$temp/new-job"); 1 }, 'duplicate runtime metadata fails');
  $changed = read_json_after_clone($receipts[1]);
  $changed->{details}{arguments}[8] = '--destination=outside/p.xml';
  ok(!eval { project_searchpaths($documents[1], $changed, "$temp/new-job"); 1 }, 'unverified output address fails');
  $changed->{details}{arguments}[8] = "--destination=$temp/new-job/wrong.xml";
  ok(!eval { project_searchpaths($documents[1], $changed, "$temp/new-job"); 1 }, 'destination must identify the actual compared XML');

  my @roots = ("$temp/corpus old", "$temp/corpus new");
  for my $i (0, 1) {
    my $job = "$roots[$i]/jobs/p-one";
    make_path($job);
    my $receipt = read_json_after_clone($receipts[$i]);
    $receipt->{status} = 'ok';
    $receipt->{counts} = { mathElements => 0, errors => 0, workerMs => $i + 1 };
    $receipt->{counts}{timedOut} = 0 if $i;
    $receipt->{details}{$_} = [] for qw(taxonomy missingFiles undefinedMacros errorNodes internalLeaks danglingRefs);
    $receipt->{details}{arguments}[7] = "--log=$job/p.log";
    $receipt->{details}{arguments}[8] = "--destination=$job/p.xml";
    write_json("$job/receipt.json", $receipt);
    write_json("$roots[$i]/run.json", { schema => 'codex-scientiae/inventory-run/0.1', jobs => 1,
        receipts => { ok => 1, failed => 0, missing => 0 }, executor => { summary => { Succeeded => 1, Total => 1, TimedOut => 0 }, errors => [] } });
    my $doc = $documents[$i]->cloneNode(1);
    my $ledger = $doc->createElementNS($capture, 'capture:ledger');
    my $math = $doc->createElementNS($capture, 'capture:math');
    $math->setAttribute($_, 0) for qw(source callsiteOnly crossSource unlocated total);
    $ledger->appendChild($math); $doc->documentElement->appendChild($ledger);
    write_raw("$job/p.xml", $doc->toString(0));
  }
  my $retained = object_hash(tree_hashes($roots[0]));
  my $compare = sub {
    my ($name, $pin, $mode, $left, $right) = @_;
    my @args = ($^X, '-I', 'lib', 'tools/dev/capture-corpus-audit.pl',
      '--baseline', $left || $roots[0], '--candidate', $right || $roots[1],
      '--output', "$temp/$name");
    push @args, '--project-baseline', $pin if defined $pin;
    push @args, '--mode', $mode if defined $mode;
    my ($stdout, $stderr);
    run3(\@args, undef, \$stdout, \$stderr);
    my $status = $?;
    write_raw("$temp/$name.log", ($stdout || '') . ($stderr || ''));
    return ($status, "$temp/$name/comparison.json");
  };
  my ($exact_status) = $compare->('corpus-exact', undef);
  isnt($exact_status, 0, 'corpus CLI retains exact path-metadata failure without a projection');
  my ($projected_status, $projected_report) = $compare->('corpus-projected', file_hash("$roots[0]/run.json"));
  is($projected_status, 0, 'corpus CLI qualifies a proven explicit relocation') or diag(read_raw("$temp/corpus-projected.log"));
  my $result = read_json($projected_report);
  ok($result->{qualified}, 'projected corpus verdict is explicit');
  is($result->{exact_document_differences}, 1, 'literal document difference remains visible in passing projected report');
  is(scalar(@{$result->{papers}[0]{derived_counts}}), 1, 'missing historical timeout count has explicit aggregate provenance');
  my $original_aggregate = read_json("$roots[0]/run.json");
  my $unproven_aggregate = read_json_after_clone($original_aggregate);
  delete $unproven_aggregate->{executor}{summary}{TimedOut};
  write_json("$roots[0]/run.json", $unproven_aggregate);
  my ($unproven_timeout) = $compare->('corpus-unproven-timeout', file_hash("$roots[0]/run.json"));
  isnt($unproven_timeout, 0, 'missing timeout observation is not guessed when aggregate evidence is absent');
  write_json("$roots[0]/run.json", $original_aggregate);
  my ($wrong_pin) = $compare->('corpus-wrong-pin', '0' x 64);
  isnt($wrong_pin, 0, 'corpus CLI rejects wrong historical run identity');
  my $mutated = read_raw("$roots[1]/jobs/p-one/p.xml"); $mutated =~ s/a b/a changed b/;
  write_raw("$roots[1]/jobs/p-one/p.xml", $mutated);
  my ($content_status) = $compare->('corpus-content-change', file_hash("$roots[0]/run.json"));
  isnt($content_status, 0, 'corpus CLI rejects manuscript drift despite valid relocation');
  $mutated =~ s/a changed b/a b/;
  write_raw("$roots[1]/jobs/p-one/p.xml", $mutated);
  my $diagnostic = read_json("$roots[1]/jobs/p-one/receipt.json");
  $diagnostic->{counts}{errors} = 1;
  write_json("$roots[1]/jobs/p-one/receipt.json", $diagnostic);
  my ($diagnostic_status) = $compare->('corpus-diagnostic-change', file_hash("$roots[0]/run.json"));
  isnt($diagnostic_status, 0, 'corpus CLI rejects diagnostic drift even when timing counters legitimately differ');
  is(object_hash(tree_hashes($roots[0])), $retained, 'corpus comparisons preserve the entire retained input run');

  my @parity = ("$temp/corpus off", "$temp/corpus on");
  for my $i (0, 1) {
    my $job = "$parity[$i]/jobs/p-one";
    make_path($job);
    my $receipt = read_json_after_clone($receipts[$i]);
    $receipt->{status} = 'ok';
    $receipt->{counts} = { mathElements => 0, errors => 0, workerMs => $i + 1, timedOut => 0 };
    $receipt->{details}{$_} = [] for qw(taxonomy missingFiles undefinedMacros errorNodes internalLeaks danglingRefs);
    if ($i == 0) {
      @{ $receipt->{details}{arguments} } = grep { $_ ne '--capture' } @{ $receipt->{details}{arguments} };
    }
    my @args = @{ $receipt->{details}{arguments} };
    $args[-3] = "--log=$job/p.log";
    $args[-2] = "--destination=$job/p.xml";
    $receipt->{details}{arguments} = \@args;
    write_json("$job/receipt.json", $receipt);
    write_json("$parity[$i]/run.json", { schema => 'codex-scientiae/inventory-run/0.1', jobs => 1,
        receipts => { ok => 1, failed => 0, missing => 0 },
        executor => { summary => { Succeeded => 1, Total => 1, TimedOut => 0 }, errors => [] } });
    my $doc = $documents[$i]->cloneNode(1);
    if ($i) {
      my $ledger = $doc->createElementNS($capture, 'capture:ledger');
      my $math = $doc->createElementNS($capture, 'capture:math');
      $math->setAttribute($_, 0) for qw(source callsiteOnly crossSource unlocated total);
      $ledger->appendChild($math); $doc->documentElement->appendChild($ledger);
    }
    write_raw("$job/p.xml", $doc->toString(0));
  }
  my $off_pin = file_hash("$parity[0]/run.json");
  my ($parity_status, $parity_report) = $compare->('corpus-parity', $off_pin, 'parity', $parity[0], $parity[1]);
  is($parity_status, 0, 'parity mode qualifies stripped off/on agreement') or diag(read_raw("$temp/corpus-parity.log"));
  my $parity_result = read_json($parity_report);
  is($parity_result->{mode}, 'parity', 'parity mode is recorded');
  ok($parity_result->{qualified}, 'parity verdict is explicit');
  my ($replay_off) = $compare->('corpus-replay-off', $off_pin, 'replay', $parity[0], $parity[1]);
  isnt($replay_off, 0, 'replay mode rejects a capture-off baseline');
  my $drift = read_raw("$parity[1]/jobs/p-one/p.xml"); $drift =~ s/a b/a changed b/;
  write_raw("$parity[1]/jobs/p-one/p.xml", $drift);
  my ($parity_drift) = $compare->('corpus-parity-drift', $off_pin, 'parity', $parity[0], $parity[1]);
  isnt($parity_drift, 0, 'parity mode rejects manuscript drift after strip');
  $drift =~ s/a changed b/a b/;
  write_raw("$parity[1]/jobs/p-one/p.xml", $drift);
  my ($swapped) = $compare->('corpus-parity-swapped', file_hash("$parity[1]/run.json"), 'parity', $parity[1], $parity[0]);
  isnt($swapped, 0, 'parity mode requires capture-off baseline and capture-on candidate');
}

sub read_json_after_clone { return JSON::PP->new->utf8->decode(json_bytes($_[0])); }

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
my $base_case = $base_report->{cases}{$keys[0]};
my $removed_case = $removed_report->{cases}{$keys[0]};
my $raw_removed = compare_case($base_case, $removed_case);
is_deeply($raw_removed, ['removed-residual'], 'raw compare still names the removal');
my $accept = {
  format => $CaptureAudit::TRANSITION_FORMAT,
  baseline_run_sha256 => 'test',
  repair => 'test-remove',
  entries => [{ driver => 'v1-driver.t', key => $keys[0],
      prior_residual => $base_case->{residual}, expected => 'removed-residual' }] };
my ($kept, $review) = review_case_issues($accept, 'v1-driver.t', $keys[0], $base_case, $removed_case, $raw_removed);
is_deeply($kept, [], 'hash-matching removal is consumed');
is($review->{expected}, 'removed-residual', 'applied transition is recorded');
my $wrong_prior = { %$accept, entries => [{ %{ $accept->{entries}[0] },
      prior_residual => { off => { stripped_sha256 => 'nope' }, on => { stripped_sha256 => 'nope' } } }] };
my ($wrong_kept) = review_case_issues($wrong_prior, 'v1-driver.t', $keys[0], $base_case, $removed_case, $raw_removed);
like(join(' ', @$wrong_kept), qr/transition-prior-residual/, 'stale residual signature is rejected');
my ($unsat) = review_case_issues($accept, 'v1-driver.t', $keys[0], $base_case, $base_case, ['changed-residual']);
like(join(' ', @$unsat), qr/transition-unsatisfied/, 'a remaining difference cannot use a removal entry');
{
  local $ENV{LATEXAI_AUDIT_TRANSITIONS} = "$temp/t-remove.json";
  write_json($ENV{LATEXAI_AUDIT_TRANSITIONS}, $accept);
  my ($ok_status, $ok_report, undef, $ok_log) = prove_driver('removed-reviewed', $base_dir, 'stable');
  is($ok_status, 0, 'listed removal does not fail the driver') or diag($ok_log);
  is($ok_report->{reviewed_transitions}[0]{expected}, 'removed-residual', 'driver records the review');
  is_deeply($ok_report->{issues}, [], 'reviewed removal is not a remaining driver issue');
}
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
{
  # A legacy canonical pair retains the ledger under a foreign root. Re-strip
  # both sides without recreating the engine run or adopting candidate output.
  my $legacy_dir = "$temp/legacy-root";
  make_path($legacy_dir);
  my $legacy = JSON::PP->new->utf8->decode(json_bytes($base_report));
  my $key = $keys[0];
  my $case = $legacy->{cases}{$key};
  my $text = '<!--keep--><text>a</text> <text>b</text>';
  for my $side (qw(off on)) {
    my $ledger = $side eq 'on' ? '<c:ledger><c:engine revision="old"></c:engine></c:ledger>' : '';
    my $file = "$key.$side.stripped.xml";
    write_raw("$legacy_dir/$file", qq{<root xmlns:c="$capture">$text$ledger</root>});
    $case->{residual}{$side} = { %{ $case->{residual}{off} }, stripped_sha256 => file_hash("$legacy_dir/$file") };
    $legacy->{artifacts} = {} if $side eq 'off';
    $legacy->{artifacts}{$file} = file_hash("$legacy_dir/$file");
  }
  write_json("$legacy_dir/report.json", $legacy);
  my $original = object_hash(tree_hashes($legacy_dir));
  XML::LibXML->new(no_blanks => 1)->load_xml(string => '<root><child/></root>');
  my $projected = restrip_report($legacy_dir, $legacy, "$temp/projected-root");
  ok(!$projected->{cases}{$key}{different}, 'legacy custom-root metadata residual disappears on both re-stripped sides')
    or diag(json_bytes($projected->{cases}{$key}{residual}));
  is(object_hash(tree_hashes($legacy_dir)), $original, 'projection preserves every original baseline byte');
  is_deeply($projected->{cases}{$key}{driver_diagnostics}, $case->{driver_diagnostics}, 'projection preserves diagnostics');
  is($projected->{cases}{$key}{off_raw_sha256}, $case->{off_raw_sha256}, 'projection preserves independent raw-byte gate');
  my $candidate = JSON::PP->new->utf8->decode(json_bytes($projected->{cases}{$key}));
  write_raw("$temp/current-root.xml", qq{<root>$text</root>});
  $candidate->{residual}{on}{stripped_sha256} = file_hash("$temp/current-root.xml");
  is_deeply(compare_case($projected->{cases}{$key}, $candidate), [], 'revision change passes under one strip implementation');
  like(read_raw("$temp/projected-root/$key.on.stripped.xml"), qr{<!--keep--><text>a</text> <text>b</text>}, 'retained canonical whitespace and comments survive re-parsing');
  $candidate->{residual}{on}{stripped_sha256} = 'manuscript-change';
  $candidate->{different} = JSON::PP::true;
  like(join(' ', @{ compare_case($projected->{cases}{$key}, $candidate) }), qr/new-residual/, 'real custom-root tree drift still fails after re-stripping');
  write_raw("$legacy_dir/$key.on.stripped.xml", '<tampered/>');
  ok(!eval { restrip_report($legacy_dir, $legacy, "$temp/corrupt-projection"); 1 }, 'corrupt legacy tree cannot be re-stripped');
  like($@, qr/corrupt evidence/, 'corrupt projection reports the integrity failure');
}
{
  write_raw($driver, driver_text('t/capture-audit/residual.tex'));
  local $ENV{LATEXAI_AUDIT_PROJECT_BASELINE} = file_hash("$base_dir/run.json");
  my ($status, $report, $out, $log) = prove_driver('explicit-restrip', $base_dir, 'known');
  is($status, 0, 'real observer re-strips an explicitly selected baseline') or diag($log);
  my $current_state = { %$state, files => { 'tools/dev/CaptureStrip.pm' => file_hash('tools/dev/CaptureStrip.pm') } };
  my $strict = finish_run($out, ['v1-driver.t'], $base_dir, 0, $current_state, $current_state,
    $ENV{LATEXAI_AUDIT_PROJECT_BASELINE});
  ok($strict->{qualified}, 'explicit projection qualifies with original baseline and current implementation identities')
    or diag(json_bytes($strict->{issues}));
  is($strict->{baseline_projection}{source_run_sha256}, file_hash("$base_dir/run.json"), 'qualification pins original baseline run');
  my $unpinned = finish_run($out, ['v1-driver.t'], $base_dir, 0, $current_state, $current_state);
  like(join(' ', @{ $unpinned->{issues} }), qr/changed-audit-implementation/, 'implicit reinterpretation remains forbidden');
  my $bad_pin = finish_run($out, ['v1-driver.t'], $base_dir, 0, $current_state, $current_state, '0' x 64);
  like(join(' ', @{ $bad_pin->{issues} }), qr/baseline-projection-pin-mismatch/, 'wrong source pin fails strict qualification');
  my $original_run = read_json("$base_dir/run.json");
  my $historical_run = read_json_after_clone($original_run);
  delete $historical_run->{comparison_contract};
  write_json("$base_dir/run.json", $historical_run);
  my $implicit_contract = finish_run($out, ['v1-driver.t'], $base_dir, 0, $current_state, $current_state);
  like(join(' ', @{$implicit_contract->{issues}}), qr/changed-comparison-contract/, 'old comparison contract cannot be silently reinterpreted');
  my $explicit_contract = finish_run($out, ['v1-driver.t'], $base_dir, 0, $current_state, $current_state,
    file_hash("$base_dir/run.json"));
  ok($explicit_contract->{qualified}, 'hash-pinned projection explicitly upgrades an old comparison contract')
    or diag(json_bytes($explicit_contract->{issues}));
  write_json("$base_dir/run.json", $original_run);
  write_raw("$out/v1-driver.t/baseline-projection/$keys[0].on.stripped.xml", '<tampered/>');
  my $bad_projection = finish_run($out, ['v1-driver.t'], $base_dir, 0, $current_state, $current_state,
    $ENV{LATEXAI_AUDIT_PROJECT_BASELINE});
  like(join(' ', @{ $bad_projection->{issues} }), qr/projection-artifact-integrity/, 'modified projected evidence fails qualification');
}
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
