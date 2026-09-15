#!/usr/bin/env perl
use strict;
use warnings;
use FindBin;
use lib $FindBin::Bin;
use CaptureAudit qw(read_json write_json file_hash tree_hashes);
use CaptureCompare qw(compare_paper);
use CaptureWhitespace qw(load_whitespace_model);
use CaptureInventory ();
use File::Path qw(make_path);
use File::Spec;
use Time::HiRes qw(time);
use JSON::PP;

my ($request_path, $output) = @ARGV;
die "usage: compare-paper.pl REQUEST_JSON NEW_OUTPUT_DIRECTORY\n" unless @ARGV == 2;
die "Output already exists\n" if -e $output;
my $started = time;
my $request = read_json($request_path);
die "Invalid paper comparison request\n" unless ($request->{schema} || '') eq 'latexai/paper-comparison-request/1'
  && ($request->{mode} || '') =~ /^(?:parity|replay|regression|styles)$/ && $request->{article}{slug}
  && ($request->{left}{condition}{id} || '') =~ /^[a-z][a-z0-9-]*$/
  && ($request->{right}{condition}{id} || '') =~ /^[a-z][a-z0-9-]*$/;
make_path($output);
my $context = {project=>1, inputs=>{$request_path=>file_hash($request_path)}};
my (@issues, $paper, $normalization);
my $complete = eval {
  my $model = $request->{model};
  $context->{whitespace} = load_whitespace_model($model->{path}, $model->{sha256});
  $normalization = $context->{whitespace}{contract};
  $context->{inputs}{$normalization->{model_path}} = $normalization->{model_sha256};
  @{$context->{inputs}}{keys %{$normalization->{implementation}}} = values %{$normalization->{implementation}};
  for my $pin ($request->{experiment}, $request->{freeze}) {
    die "Changed comparison input\n" unless file_hash($pin->{path}) eq $pin->{sha256};
    $context->{inputs}{$pin->{path}} = $pin->{sha256};
  }
  my (@evidence, @jobs, @xml);
  for my $side (qw(left right)) {
    my $input = $request->{$side};
    my $c = $input->{condition};
    die "Condition $c->{id} is not complete\n" unless $c->{status} eq 'ok'
      && $c->{execution}{outcome} eq 'exited' && defined($c->{execution}{exitCode}) && $c->{execution}{exitCode} == 0
      && defined($c->{execution}{timedOut}) && !$c->{execution}{timedOut} && $c->{execution}{cleanupComplete};
    my %seen;
    for my $artifact (@{$input->{artifacts}}) {
      die "Duplicate comparison artifact\n" if $seen{$artifact->{path}}++;
      my $path = CaptureInventory::owned_path($request->{paperDirectory}, $artifact->{path});
      die "Changed comparison artifact: $path\n" unless file_hash($path) eq $artifact->{sha256} && -s $path == $artifact->{bytes};
      $context->{inputs}{$path} = $artifact->{sha256};
    }
    die "Missing recorded XML\n" unless $seen{$c->{outputs}{xml}};
    my $source = $c->{details}{sourceTree} || $request->{source};
    my $job = File::Spec->catdir($request->{paperDirectory}, 'conditions', $c->{id});
    if ($c->{conversion}) {
      my $conversion = $c->{conversion};
      my $pin = $conversion->{action} eq 'reused' ? $conversion->{origin}{freeze} : ($conversion->{freeze} || $request->{freeze});
      die "Changed conversion freeze\n" unless file_hash($pin->{path}) eq $pin->{sha256};
      $context->{inputs}{$pin->{path}} = $pin->{sha256};
      my $freeze = read_json($pin->{path});
      my @sources = grep {$_->{article}{directory} eq $request->{article}{directory}} @{$freeze->{sources}};
      die "Conversion evidence roots disagree\n" unless @sources == 1
        && $source eq $sources[0]{tree}{root} && $c->{engine}{root} eq $freeze->{engine}
        && $c->{details}{perl} eq $freeze->{perl} && $conversion->{identity}{source} eq $sources[0]{tree}{sha256};
      if ($conversion->{action} eq 'reused') {
        my $origin = $conversion->{origin}{record};
        die "Changed conversion origin\n" unless file_hash($origin->{path}) eq $origin->{sha256};
        $context->{inputs}{$origin->{path}} = $origin->{sha256};
        $job = $c->{details}{conversionWorkingDirectory};
      }
    }
    if ($c->{legacy}) {
      my $legacy=$c->{legacy};
      die "Unknown legacy import rule\n" unless $legacy->{rule} eq 'receipt-native-fields/1';
      for my $pin ($legacy->{batch}, $legacy->{receipt}, @{$legacy->{raw}}) {
        die "Changed legacy input\n" unless file_hash($pin->{path}) eq $pin->{sha256};
        $context->{inputs}{$pin->{path}}=$pin->{sha256};
      }
      my $receipt=read_json($legacy->{receipt}{path});
      die "Legacy article mismatch\n" unless $receipt->{article}{treeSha256} eq $request->{article}{treeSha256};
      require File::Basename;
      $job=File::Basename::dirname($legacy->{receipt}{path});
    }
    push @jobs, $job;
    push @xml, CaptureInventory::owned_path($request->{paperDirectory}, $c->{outputs}{xml});
    my $evidence = {
      article=>{map {$_=>$request->{article}{$_}} qw(slug directory treeSha256)}, sourceTree=>$source,
      status=>'ok', counts=>$c->{counts}, details=>$c->{details}, engine_root=>$c->{engine}{root},
      ($c->{conversion} ? (conversion_identity=>$c->{conversion}{identity}) : ())
    };
    delete $evidence->{sourceTree} if $c->{legacy} && $c->{legacy}{invocationContract} eq 'receipt-source-cwd';
    push @evidence, $evidence;
  }
  $paper = compare_paper($context, $request->{article}{slug}, @evidence,
    @jobs, $output, mode=>$request->{mode}, old_xml=>$xml[0], new_xml=>$xml[1]);
  push @issues, @{$paper->{issues}};
  1;
};
push @issues, "incomplete:$@" unless $complete;
for my $path (sort keys %{$context->{inputs}}) {
  if (!-f $path || file_hash($path) ne $context->{inputs}{$path}) { push @issues, "input-changed:$path"; $complete=0; }
}
my $status = !$complete ? 'incomplete' : @issues ? 'fail' : 'pass';
write_json("$output/comparison.json", {
  schema=>'latexai/paper-comparison/1', mode=>$request->{mode}, left=>$request->{left}{condition}{id}, right=>$request->{right}{condition}{id},
  status=>$status, qualified=>$status eq 'pass' ? JSON::PP::true : JSON::PP::false, issues=>\@issues, paper=>$paper,
  normalization=>$normalization, inputs=>$context->{inputs}, durationMs=>1000*(time-$started),
  policy=>{configuration_difference=>{parity=>'capture',replay=>'none',regression=>'engine lib/bin/lib-ctan',styles=>'includestyles'}->{$request->{mode}},
    output_differences=>($request->{mode} eq 'styles' ? 'observations' : 'fail'),
    required_invariants=>[qw(complete-native-execution raw-artifact-integrity recorded-invocation source-byte-fidelity)]},
  comparator=>tree_hashes(qw(tools/dev/compare-paper.pl tools/dev/CaptureCompare.pm tools/dev/CaptureAudit.pm tools/dev/CaptureRuntime.pm tools/dev/CaptureStrip.pm tools/dev/CaptureWhitespace.pm tools/dev/CaptureInventory.pm))
});
print "Paper comparison: $request->{article}{slug}, $request->{mode}, $status, ",scalar(@issues)," issues\n";
print "ISSUE $_\n" for @issues;
exit($status eq 'pass' ? 0 : $status eq 'fail' ? 1 : 2);
