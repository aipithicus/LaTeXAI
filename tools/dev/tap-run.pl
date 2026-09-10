#!/usr/bin/env perl
# tools/dev/tap-run.pl — serial TAP::Harness bridge for scripts/test-worker.ps1.
# Writes TAP as tests run and a JSON result at the end. Native TAP semantics
# are preserved; formatted summaries are not parsed. One process, one job;
# TAP::Harness jobs is 1 so this is not a second scheduler.
use strict;
use warnings;
use utf8;
use File::Path qw(make_path);
use File::Spec;
use Getopt::Long qw(GetOptions);
use JSON::PP;
use TAP::Harness;
use Time::HiRes qw(gettimeofday tv_interval);

GetOptions(
  'lib=s@'    => \my @libs,
  'tap=s'     => \my $tap_path,
  'result=s'  => \my $result_path,
  'cwd=s'     => \my $cwd,
) or die "usage: tap-run.pl --tap PATH --result PATH [--lib DIR] [--cwd DIR] DRIVER...\n";

my @tests = @ARGV;
die "tap-run.pl: no drivers\n" unless @tests;
die "tap-run.pl: --tap is required\n" unless $tap_path;
die "tap-run.pl: --result is required\n" unless $result_path;

if ($cwd) {
  chdir $cwd or die "tap-run.pl: chdir $cwd: $!\n";
}

for my $path ($tap_path, $result_path) {
  my ($vol, $dir, $file) = File::Spec->splitpath($path);
  my $parent = File::Spec->catpath($vol, $dir, '');
  make_path($parent) if $parent ne '';
}

open(my $tap_fh, '>:raw', $tap_path) or die "tap-run.pl: write $tap_path: $!\n";
$tap_fh->autoflush(1);

delete $ENV{HARNESS_OPTIONS};
delete $ENV{HARNESS_TIMER};
$ENV{HARNESS_PERL_SWITCHES} = '' if exists $ENV{HARNESS_PERL_SWITCHES};

my @observations;
my $harness = TAP::Harness->new({
  verbosity => 1,
  lib       => (@libs ? \@libs : ['lib']),
  merge     => 0,
  jobs      => 1,
  color     => 0,
  errors    => 1,
  stdout    => $tap_fh,
});
$harness->callback(after_test => sub {
    my ($job, $parser) = @_;
    my $file = ref $job eq 'ARRAY' ? $job->[0] : $job;
    my $skip_all = $parser->skip_all;
    $skip_all = undef if defined $skip_all && $skip_all eq '';
    push @observations, {
      file           => $file,
      passed         => [ $parser->passed ],
      failed         => [ $parser->failed ],
      skipped        => [ $parser->skipped ],
      todo           => [ $parser->todo ],
      skip_all       => $skip_all,
      tests_planned  => $parser->tests_planned,
      tests_run      => $parser->tests_run,
      parse_errors   => [ $parser->parse_errors ],
      is_good_plan   => $parser->is_good_plan ? JSON::PP::true : JSON::PP::false,
      exit           => $parser->exit,
      wait           => $parser->wait,
      has_problems   => $parser->has_problems ? JSON::PP::true : JSON::PP::false,
    };
  });

my $started = [gettimeofday];
my $aggregator = $harness->runtests(@tests);
my $elapsed = tv_interval($started);
close $tap_fh or die "tap-run.pl: close $tap_path: $!\n";

my $incomplete = 0;
for my $row (@observations) {
  my $planned = $row->{tests_planned};
  my $ran     = $row->{tests_run} // 0;
  my $skip    = $row->{skip_all};
  if (!defined $skip && (!defined $planned || ($planned == 0 && $ran == 0 && !@{ $row->{parse_errors} } && !$row->{is_good_plan}))) {
    $incomplete = 1;
  }
  if (@{ $row->{parse_errors} }) { $incomplete = 1 unless $row->{skip_all}; }
}

my $result = {
  schema => 'latexai/tap-job/0.1',
  complete => JSON::PP::true,
  perl => $^X,
  drivers => [@tests],
  aggregator => {
    passed       => 0 + $aggregator->passed,
    failed       => 0 + $aggregator->failed,
    skipped      => 0 + $aggregator->skipped,
    todo         => 0 + $aggregator->todo,
    parse_errors => 0 + $aggregator->parse_errors,
    has_problems => $aggregator->has_problems ? JSON::PP::true : JSON::PP::false,
    all_passed   => $aggregator->all_passed ? JSON::PP::true : JSON::PP::false,
    status       => $aggregator->get_status,
    elapsed      => 0 + $elapsed,
  },
  tests => \@observations,
  incomplete => $incomplete ? JSON::PP::true : JSON::PP::false,
};

open(my $json_fh, '>:raw', $result_path) or die "tap-run.pl: write $result_path: $!\n";
print {$json_fh} JSON::PP->new->canonical->utf8->pretty->encode($result);
close $json_fh or die "tap-run.pl: close $result_path: $!\n";

my $failed = $aggregator->has_problems || $incomplete;
exit($failed ? 1 : 0);
