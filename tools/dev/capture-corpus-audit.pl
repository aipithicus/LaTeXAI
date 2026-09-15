#!/usr/bin/env perl
use strict;
use warnings;
use lib 'tools/dev';
use CaptureAudit qw(read_json write_json read_raw file_hash object_hash);
use CaptureStrip qw(without_capture);
use XML::LibXML;
use XML::LibXML::XPathContext;
use File::Spec;
use File::Basename qw(dirname);
use File::Path qw(make_path);
use File::Glob qw(bsd_glob);
use Cwd qw(abs_path);
use Getopt::Long qw(GetOptions);
use CaptureRuntime qw(project_searchpaths);
use CaptureInventory qw(load_inventory);
use CaptureCompare qw(compare_paper);
use Encode qw(decode encode FB_DEFAULT);
use JSON::PP;
my ($baseline_root, $current_root, $output, $projection_pin, $mode, $model_path, $model_pin);
my ($baseline_format, $candidate_format, $baseline_condition, $candidate_condition) = ('paper-run', 'paper-run', 'conversion', 'conversion');
GetOptions('baseline=s' => \$baseline_root, 'candidate=s' => \$current_root,
  'output=s' => \$output, 'project-baseline=s' => \$projection_pin, 'mode=s' => \$mode,
  'whitespace-model=s' => \$model_path, 'whitespace-model-sha256=s' => \$model_pin,
  'baseline-format=s' => \$baseline_format, 'candidate-format=s' => \$candidate_format,
  'baseline-condition=s' => \$baseline_condition, 'candidate-condition=s' => \$candidate_condition)
  or die "Invalid arguments\n";
$mode = 'replay' unless defined $mode;
die "usage: capture-corpus-audit.pl --baseline RUN --candidate RUN --output NEW_DIR [--mode replay|parity] [--baseline-format paper-run|legacy] [--candidate-format paper-run|legacy] [--baseline-condition ID] [--candidate-condition ID] [--project-baseline RECORD_SHA256] [--whitespace-model FILE --whitespace-model-sha256 SHA256]\n"
  unless $baseline_root && $current_root && $output && !@ARGV;
die "Unknown mode\n" unless $mode eq 'replay' || $mode eq 'parity';
$baseline_root = abs_path($baseline_root) or die "Baseline missing\n";
$current_root = abs_path($current_root) or die "Candidate missing\n";
die "Output already exists\n" if -e $output;
my $proposed = File::Spec->rel2abs($output); $proposed =~ s{\\}{/}g;
for my $input ($baseline_root, $current_root) {
  die "Output must be outside input runs\n" if index(lc($proposed) . '/', lc($input) . '/') == 0;
}
die "Unknown inventory format\n" if grep { $_ ne 'paper-run' && $_ ne 'legacy' } ($baseline_format, $candidate_format);
my $source_pin = file_hash("$baseline_root/" . ($baseline_format eq 'legacy' ? 'run.json' : 'batch.json'));
die "Wrong baseline pin\n" if defined($projection_pin) && $projection_pin ne $source_pin;
my %input_hashes;
my $whitespace;
if (defined($model_path) || defined($model_pin)) {
  die "Whitespace normalization requires model, model pin and baseline pin\n"
    unless defined($model_path) && defined($model_pin) && defined($projection_pin);
  require CaptureWhitespace;
  $whitespace = CaptureWhitespace::load_whitespace_model($model_path, $model_pin);
  $input_hashes{$whitespace->{contract}{model_path}} = $model_pin;
  @input_hashes{keys %{$whitespace->{contract}{implementation}}} = values %{$whitespace->{contract}{implementation}};
}
sub retained_json {
  my ($path) = @_;
  $input_hashes{$path} = file_hash($path);
  return read_json($path);
}
sub retained_hash { my ($path) = @_; return $input_hashes{$path} = file_hash($path); }
my @issues;
my @loaded = (
  load_inventory($baseline_root, format=>$baseline_format, condition=>$baseline_condition, read_json=>\&retained_json, file_hash=>\&retained_hash),
  load_inventory($current_root, format=>$candidate_format, condition=>$candidate_condition, read_json=>\&retained_json, file_hash=>\&retained_hash));
my @runs = map { $_->{run} } @loaded;
for my $i (0, 1) {
  push @issues, map { "run-$i:$_" } @{$loaded[$i]{issues}};
}
make_path($output);
my $parity = $mode eq 'parity';
my $context = {project=>defined($projection_pin), whitespace=>$whitespace, inputs=>\%input_hashes};
my @papers;
my @inventories = map { $_->{papers} } @loaded;
push @issues, 'changed-paper-selection' unless object_hash([sort keys %{ $inventories[0] }])
  eq object_hash([sort keys %{ $inventories[1] }]);
for my $slug (sort keys %{ $inventories[0] }) {
  next unless $inventories[1]{$slug};
  my ($old_job, $job) = map { $_->{$slug}{directory} } @inventories;
  my ($old_receipt, $new_receipt) = map { $_->{$slug}{receipt} } @inventories;
  my @counts = ({ %{ $old_receipt->{counts} } }, { %{ $new_receipt->{counts} } });
  my @derived_counts;
  if (defined $projection_pin) {
    for my $i (0, 1) {
      next unless $loaded[$i]{format} eq 'legacy';
      my $summary = $runs[$i]{executor}{summary};
      if (!exists($counts[$i]{timedOut}) && exists($summary->{TimedOut}) && $summary->{TimedOut} == 0
          && $summary->{Succeeded} == $runs[$i]{jobs} && $summary->{Total} == $runs[$i]{jobs}) {
        $counts[$i]{timedOut} = 0;
        push @derived_counts, { side => $i ? 'candidate' : 'baseline', field => 'timedOut', value => 0,
          source => 'run.executor.summary.TimedOut', source_run_sha256 => $input_hashes{($i ? $current_root : $baseline_root) . '/run.json'} };
      }
    }
  }
  my $paper = compare_paper($context, $slug, $old_receipt, $new_receipt, $old_job, $job, $output,
    mode=>$mode, counts=>\@counts, derived_counts=>\@derived_counts);
  push @issues, @{$paper->{issues}};
  push @papers, $paper;
}
for my $path (sort keys %input_hashes) {
  push @issues, "input-changed:$path" unless file_hash($path) eq $input_hashes{$path};
}
my $exact_differences = scalar(grep { !$_->{exact_document_equal} } @papers);
write_json("$output/comparison.json", { schema => 'latexai/corpus-comparison/3',
  mode => $mode, baseline => $baseline_root, candidate => $current_root,
  inventory_formats => [$baseline_format, $candidate_format], conditions => [$baseline_condition, $candidate_condition],
  baseline_projection => defined($projection_pin) ? { source_run_sha256 => $source_pin } : undef,
  normalization => $whitespace ? $whitespace->{contract} : undef,
  inputs => \%input_hashes, comparator => CaptureAudit::tree_hashes(qw(tools/dev/CaptureCompare.pm tools/dev/capture-corpus-audit.pl tools/dev/CaptureInventory.pm tools/dev/CaptureRuntime.pm tools/dev/CaptureStrip.pm tools/dev/CaptureAudit.pm)),
  papers => \@papers, exact_document_differences => $exact_differences,
  issues => \@issues, qualified => @issues ? JSON::PP::false : JSON::PP::true });
for my $paper (@papers) {
  if ($parity) {
    printf "%s: %d math, tree=%s\n", $paper->{paper},
      scalar(keys %{ $paper->{after}{math_tex} }),
      $paper->{comparison_document_equal} ? 'equal' : 'differ';
  }
  else {
    printf "%s: %d carriers, %d changed capture records, %d source ranges checked\n", $paper->{paper},
      scalar(keys %{ $paper->{after}{carriers} }), scalar(@{ $paper->{changes} }), $paper->{after}{source_ranges_checked};
  }
}
print "ISSUE $_\n" for @issues;
printf "CorpusAudit compare (%s): %d papers, %d exact document differences, %d gate issues\n",
  $mode, scalar(@papers), $exact_differences, scalar(@issues);
exit(@issues ? 1 : 0);
