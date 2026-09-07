#!/usr/bin/env perl
use strict;
use warnings;
use FindBin;
use lib "$FindBin::RealBin/../../lib";
use LaTeXAI::Post;
use LaTeXAI::Post::Markdown;
use Time::HiRes qw(time);
use Digest::SHA qw(sha256_hex);
use Encode qw(encode);
use JSON::PP;

# Warning I/O can dominate a traversal; refuse a contaminated measurement.
$SIG{__WARN__} = sub { die @_ };

my ($input, $strategy, $repeats, $output, $report, $asset_root) = @ARGV;
die "Usage: markdown-benchmark.pl input.xml deferred|indexed repeats output.md report.json asset-root\n"
  unless @ARGV == 6 && $repeats =~ /^\d+$/ && $repeats >= 3;
my $start = time;
my $dom = LaTeXAI::Post->load_file($input);
my $parse_ms = 1000 * (time - $start);
my $dom_hash = sha256_hex($dom->toString);
my $projector = LaTeXAI::Post::Markdown->new(asset_root => $asset_root);
my $warm = $projector->project($dom, strategy => $strategy);
my $expected = sha256_hex(encode('UTF-8', $warm->{markdown}));
undef $warm;
my (@samples, $last);
for (1 .. $repeats) {
  undef $last;
  my $call_start = time;
  $last = $projector->project($dom, strategy => $strategy);
  my $call_ms = 1000 * (time - $call_start);
  die "Non-deterministic Markdown\n" unless sha256_hex(encode('UTF-8', $last->{markdown})) eq $expected;
  push @samples, { %{$last->{report}{timings_ms}}, call => $call_ms };
}
die "Projection changed the prepared DOM\n" unless sha256_hex($dom->toString) eq $dom_hash;
my %medians;
for my $phase (qw(index walk finalize total call)) {
  my @v = sort { $a <=> $b } map { $_->{$phase} } @samples;
  $medians{$phase} = @v % 2 ? $v[int(@v/2)] : ($v[@v/2-1]+$v[@v/2])/2;
}
my $result = { schema => 'latexai/markdown-benchmark-worker/0.1', input => $input,
  strategy => $strategy, repetitions => 0+$repeats, parse_ms => $parse_ms,
  samples_ms => \@samples, medians_ms => \%medians, dom_unchanged => JSON::PP::true,
  output_sha256 => $expected, projection => $last->{report}, perl => "$^V", libxml => "$XML::LibXML::VERSION" };
open my $out, '>:raw', $output or die "$output: $!\n";
print {$out} encode('UTF-8', $last->{markdown}); close $out or die "$output: $!\n";
open my $rep, '>:raw', $report or die "$report: $!\n";
print {$rep} JSON::PP->new->canonical->pretty->utf8->encode($result); close $rep or die "$report: $!\n";
