#!/usr/bin/env perl
use strict;
use warnings;
use FindBin;
use File::Spec;
use File::Basename qw(basename dirname);
use File::Path qw(make_path);
use Cwd qw(abs_path);
use Getopt::Long qw(GetOptions);
use lib File::Spec->catdir($FindBin::RealBin, '..', '..', 'lib');
use lib $FindBin::RealBin;
use CaptureAudit qw(snapshot write_json write_raw finish_run file_hash read_json);
use IPC::Run3;

my $mode = shift @ARGV || '';
my ($output, $baseline, $legacy, $restrip_pin);
my $jobs = 1;
GetOptions('output=s' => \$output, 'baseline=s' => \$baseline, 'legacy-off=s' => \$legacy, 'jobs=i' => \$jobs,
  'restrip-baseline=s' => \$restrip_pin)
  or die "Invalid audit arguments\n";
die "usage: $0 record|compare --output NEW_DIR [--baseline DIR] [--restrip-baseline RUN_SHA256] [--legacy-off DIR] [t/driver.t ...]\n"
  unless $mode =~ /^(record|compare)$/ && $output && (($mode eq 'compare') == !!$baseline);
die "--jobs must be a positive integer\n" unless $jobs > 0;
die "Output must be a new directory: $output\n" if -e $output;
$baseline = abs_path($baseline) or die "Baseline directory missing\n" if $baseline;
if (defined $restrip_pin) {
  die "--restrip-baseline requires compare and the original qualified run.json SHA-256\n"
    unless $mode eq 'compare' && $restrip_pin =~ /^[0-9a-f]{64}$/
    && file_hash("$baseline/run.json") eq $restrip_pin && read_json("$baseline/run.json")->{qualified};
}
$legacy = abs_path($legacy) or die "Legacy baseline directory missing\n" if $legacy;
my @paths = @ARGV ? @ARGV : sort glob('t/*.t');
die "No drivers selected\n" unless @paths;
my %names;
for my $path (@paths) {
  die "Expected a test driver: $path\n" unless -f $path && $path =~ /\.t$/;
  die "Duplicate driver name: $path\n" if $names{basename($path)}++;
}
my @drivers = map { basename($_) } @paths;
my $proposed_output = File::Spec->rel2abs($output);
$proposed_output =~ s{\\}{/}g;
die "Comparison output must be outside its baseline\n"
  if $baseline && index(lc($proposed_output) . '/', lc($baseline) . '/') == 0;
make_path($output);
$output = abs_path($output);
die "Comparison output must be outside its baseline\n"
  if $baseline && index(lc($output) . '/', lc($baseline) . '/') == 0;
local $ENV{LATEXAI_AUDIT_OUTPUT} = $output;
local $ENV{LATEXAI_AUDIT_BASELINE} = $baseline;
local $ENV{LATEXAI_AUDIT_LEGACY_OFF} = $legacy;
local $ENV{LATEXAI_AUDIT_RESTRIP_BASELINE} = $restrip_pin;
local $ENV{LATEXAI_RUNSTAMP} = basename($output);
local $ENV{LATEXAI_AUDIT_JOBS} = $jobs;
my $before = snapshot();
write_json("$output/input.json", $before);
write_json("$output/selection.json", { paths => \@paths, drivers => \@drivers, workers => $jobs });
my $prove = File::Spec->catfile(dirname($^X), 'prove');
die "No prove script beside the selected Perl: $prove\n" unless -f $prove;
my ($stdout, $stderr);
my @command = ($^X, $prove, '-Ilib', '-j', $jobs, '--exec', qq{"$^X" -I lib -I tools/dev -MCaptureOffAudit}, @paths);
my $started = eval { run3(\@command, undef, \$stdout, \$stderr); 1 };
my $status = $?;
my $error = $@;
write_raw("$output/prove.stdout", $stdout || '');
write_raw("$output/prove.stderr", $stderr || $error || '');
print $stdout if defined $stdout;
print STDERR $stderr if defined $stderr;
warn $error if $error;
my $after = snapshot();
write_json("$output/input-after.json", $after);
my $run = finish_run($output, \@drivers, $baseline, $started && !$status ? 0 : 1, $before, $after, $restrip_pin);
printf "CaptureAudit %s: %d audited, %d residuals, %d skips, %d gate issues\n",
  $mode, @$run{qw(audited different skipped)}, scalar(@{ $run->{issues} });
print "  $_\n" for @{ $run->{issues} };
exit($run->{qualified} ? 0 : 1);
