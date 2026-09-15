package CaptureInventory;
use strict;
use warnings;
use Exporter 'import';
use File::Spec;
use File::Basename qw(dirname);
use File::Glob qw(bsd_glob);
use File::Find ();
use Cwd qw(abs_path);
use CaptureAudit qw(read_json file_hash object_hash);
our @EXPORT_OK = qw(load_inventory);

sub owned_path {
  my ($root, $relative) = @_;
  die "Invalid record-relative path\n" unless defined($relative) && length($relative)
    && $relative !~ /[\\:]/ && !grep { $_ eq '' || $_ eq '.' || $_ eq '..' } split('/', $relative, -1);
  my $path = File::Spec->catfile($root, split('/', $relative));
  my $resolved = abs_path($path) or die "Missing retained artifact: $path\n";
  my $base = abs_path($root); $base =~ tr{\\}{/}; $resolved =~ tr{\\}{/};
  die "Artifact escapes record owner\n" unless index(lc($resolved), lc($base) . '/') == 0;
  return $resolved;
}

sub load_inventory {
  my ($root, %options) = @_;
  my $format = $options{format} || 'paper-run';
  die "Unknown inventory format\n" unless $format eq 'paper-run' || $format eq 'legacy';
  my $read = $options{read_json} || \&read_json;
  my $hash = $options{file_hash} || \&file_hash;
  my $condition = $options{condition} || 'conversion';
  my $require_xml = exists($options{require_xml}) ? $options{require_xml} : 1;
  my (%papers, @issues);
  my $register = sub {
    my ($slug, $paper) = @_;
    die "Invalid or duplicate paper identity\n" unless $slug && $slug =~ /^[\w.-]+$/ && !$papers{$slug};
    $papers{$slug} = $paper;
  };
  if ($format eq 'legacy') {
    my $run = $read->("$root/run.json");
    push @issues, 'incomplete' unless ($run->{schema} || '') eq 'codex-scientiae/inventory-run/0.1'
      && $run->{jobs} && $run->{receipts}{ok} == $run->{jobs} && !$run->{receipts}{failed} && !$run->{receipts}{missing}
      && $run->{executor}{summary}{Succeeded} == $run->{jobs} && !@{$run->{executor}{errors}};
    for my $path (bsd_glob("$root/jobs/*/receipt.json")) {
      my $receipt = $read->($path);
      my $slug = $receipt->{article}{slug};
      $register->($slug, { receipt=>$receipt, directory=>dirname($path), record=>$path, legacy=>1 });
    }
    push @issues, 'receipt-coverage' unless keys(%papers) == $run->{jobs};
    return { papers=>\%papers, run=>$run, issues=>\@issues, format=>$format };
  }
  my $batch = $read->("$root/batch.json");
  die "Expected inventory-batch/1; select legacy format explicitly for old runs\n"
    unless ($batch->{schema} || '') eq 'codex-scientiae/inventory-batch/1';
  my $check = sub {
    my ($reference, $path) = @_;
    die "Invalid artifact reference\n" unless ref($reference) eq 'HASH' && ($reference->{sha256} || '') =~ /^[0-9a-f]{64}$/;
    die "Changed artifact: $path\n" unless $hash->($path) eq $reference->{sha256};
    die "Artifact length mismatch: $path\n" if exists($reference->{bytes}) && -s $path != $reference->{bytes};
  };
  $check->($batch->{experiment}, "$root/experiment.json");
  $check->($batch->{executor}, "$root/executor-execution.json");
  die "Batch references another experiment\n" unless abs_path($batch->{experiment}{path}) eq abs_path("$root/experiment.json");
  die "Batch references another executor\n" unless abs_path($batch->{executor}{path}) eq abs_path("$root/executor-execution.json");
  my $plan = $read->("$root/experiment.json");
  my $executor = $read->("$root/executor-execution.json");
  die "Invalid inventory experiment\n" unless ($plan->{schema} || '') eq 'codex-scientiae/inventory-experiment/1'
    && ref($plan->{assignments}) eq 'ARRAY' && @{$plan->{assignments}} && ref($batch->{records}) eq 'ARRAY';
  my $expected = scalar @{$plan->{assignments}};
  die "Batch engine mismatch\n" unless $batch->{engine} eq $plan->{engine};
  push @issues, 'incomplete' unless ($batch->{status} || '') eq 'complete' && $batch->{coverage}{expected} == $expected
    && $batch->{coverage}{complete} == $expected && !@{$batch->{issues}}
    && ($executor->{cleanup}{State} || '') eq 'Confirmed' && $executor->{summary}{Succeeded} == $expected && !@{$executor->{errors}};
  push @issues, 'record-coverage' unless @{$batch->{records}} == $expected;
  my (%ids, %attempts, %paths, %states, %totals);
  for my $assignment (@{$plan->{assignments}}) {
    die "Duplicate experiment assignment\n" if $ids{$assignment->{jobId}}++ || $attempts{$assignment->{attemptId}}++ || $paths{$assignment->{record}}++;
    my @rows = grep { $_->{jobId} eq $assignment->{jobId} && $_->{attemptId} eq $assignment->{attemptId} && $_->{path} eq $assignment->{record} } @{$batch->{records}};
    die "Missing or duplicate worker record reference\n" unless @rows == 1;
    my $row = $rows[0];
    $states{$row->{state}}++;
    my @outcomes = grep { $_->{id} eq $assignment->{jobId} } @{$executor->{results}};
    if (@outcomes == 1) {
      my $outcome = $outcomes[0];
      die "Batch executor observation mismatch\n" unless ref($row->{executor}) eq 'HASH'
        && $row->{executor}{state} eq $outcome->{state}
        && object_hash($row->{executor}{exitCode}) eq object_hash($outcome->{exitCode})
        && object_hash($row->{executor}{errors}) eq object_hash($outcome->{errors});
      push @issues, "executor-outcome:$assignment->{jobId}" unless $outcome->{state} eq 'Succeeded'
        && (!defined($outcome->{exitCode}) || $outcome->{exitCode} == 0) && !@{$outcome->{errors}};
    } else { push @issues, "executor-coverage:$assignment->{jobId}"; }
    push @issues, "record-issues:$assignment->{jobId}" if @{$row->{issues}};
    if ($row->{state} ne 'complete' && $row->{state} ne 'failed') { push @issues, "record-$row->{state}:$assignment->{article}{slug}"; next; }
    my $path = owned_path($root, $row->{path});
    $check->($row, $path);
    my $record = $read->($path);
    die "Wrong worker record identity\n" unless ($record->{schema} || '') eq 'codex-scientiae/paper-run/1'
      && $record->{jobId} eq $assignment->{jobId} && $record->{attemptId} eq $assignment->{attemptId}
      && object_hash($record->{article}) eq object_hash($assignment->{article})
      && object_hash($record->{experiment}) eq object_hash($batch->{experiment})
      && object_hash($record->{producer}{worker}) eq object_hash($plan->{worker})
      && $record->{producer}{engine} eq $plan->{engine} && $record->{status} eq $row->{state};
    die "Batch worker summary mismatch\n" unless object_hash($row->{summary}) eq object_hash($record->{summary});
    $totals{$_} += $record->{summary}{$_} for keys %{$record->{summary}};
    die "Expected LaTeXAI paper payload\n" unless ($record->{payload}{schema} || '') eq 'latexai/paper-experiment/1';
    my %artifacts;
    for my $artifact (@{$record->{artifacts}}) {
      die "Duplicate paper artifact\n" if $artifacts{$artifact->{path}}++;
      $check->($artifact, owned_path(dirname($path), $artifact->{path}));
    }
    my @conditions = grep { $_->{id} eq $condition } @{$record->{payload}{conditions}};
    die "Missing or duplicate condition: $condition\n" unless @conditions == 1;
    my $c = $conditions[0];
    my $slug = $record->{article}{slug};
    my $xml;
    if ($c->{outputs}{xml}) {
      die "Unrecorded condition XML\n" unless $artifacts{$c->{outputs}{xml}}
        && index($c->{outputs}{xml}, "conditions/$condition/") == 0;
      $xml = owned_path(dirname($path), $c->{outputs}{xml});
      die "Unexpected condition XML name\n" unless $xml =~ m{/\Q$slug\E\.xml$};
    } elsif ($require_xml) { push @issues, "missing-xml:$slug:$condition"; next; }
    my $ok = $record->{status} eq 'complete' && $c->{status} eq 'ok' && $c->{execution}{outcome} eq 'exited'
      && defined($c->{execution}{exitCode}) && $c->{execution}{exitCode} == 0
      && defined($c->{execution}{timedOut}) && !$c->{execution}{timedOut} && $c->{execution}{cleanupComplete};
    # Internal view for the existing comparator; no legacy receipt is written.
    my $evidence = {
      article=>{map { $_=>$record->{article}{$_} } qw(slug directory treeSha256)}, entrypoint=>$record->{article}{entrypoint},
      sourceTree=>($c->{details}{sourceTree} || $record->{article}{sourceTree}),
      engine=>$record->{producer}{engine}, engineVersion=>$c->{engine}{version}, engineCommit=>$c->{engine}{commit},
      status=>($ok ? 'ok' : 'failed'), counts=>$c->{counts}, details=>$c->{details}
    };
    if ($c->{conversion}) {
      $evidence->{conversion_identity} = $c->{conversion}{identity};
      $evidence->{engine_root} = $c->{engine}{root};
      if ($c->{conversion}{action} eq 'reused') {
        $check->($_, $_->{path}) for @{$c->{conversion}{origin}}{qw(record experiment freeze)};
        $evidence->{conversion_job} = $c->{details}{conversionWorkingDirectory};
      }
    }
    $register->($slug, { receipt=>$evidence, directory=>dirname($xml || $path), record=>$path, condition=>$condition, legacy=>0 });
  }
  for my $state (qw(complete failed nonterminal missing invalid)) {
    die "Batch coverage mismatch\n" unless ($states{$state} || 0) == $batch->{coverage}{$state};
  }
  die "Batch totals mismatch\n" unless keys(%totals) == keys(%{$batch->{totals}})
    && !grep { !exists($batch->{totals}{$_}) || $totals{$_} != $batch->{totals}{$_} } keys %totals;
  push @issues, 'unexpected-records' if $batch->{coverage}{unexpected};
  my %expected_paths = map { lc(File::Spec->rel2abs($_->{record}, $root)) => 1 } @{$plan->{assignments}};
  my $unexpected = 0;
  File::Find::find({no_chdir=>1, wanted=>sub {
    return unless -f $_ && /[\\\/]run\.json$/;
    $unexpected++ unless $expected_paths{lc(File::Spec->rel2abs($_))};
  }}, "$root/jobs") if -d "$root/jobs";
  die "Batch unexpected-record coverage mismatch\n" unless $unexpected == $batch->{coverage}{unexpected};
  push @issues, 'executor-coverage' unless @{$executor->{results}} == $expected;
  push @issues, 'record-coverage' unless keys(%papers) == $expected;
  return { papers=>\%papers, run=>$batch, issues=>\@issues, format=>$format };
}
1;
