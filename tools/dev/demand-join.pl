#!/usr/bin/env perl
# tools/dev/demand-join.pl
#
# Join the TeXdig static package census with the binding state of this
# repository, so demand and coverage sit in one table.
#
# The census is produced by aipithicus-issues/TeXdig/gauntlet-audit/scripts/
# census-sweep.ps1 as package-priority-regen.csv: per package, occurrences and
# paper counts, split by whether the \usepackage came from the paper's own .tex
# (tex_origin_papers) or from a shipped .sty/.cls (support_origin_papers). Its
# registry_covered column is TeXdig's registry, not this repository; this
# script ignores it and adds the binding state from lib/LaTeXML/Package/.
#
# Binding state, from the file itself (the coverage manifest is still deferred):
#   native       a binding exists and executes no raw TeX
#   hybrid       a binding exists and contains a live InputDefinitions( call
#   passthrough  a binding exists and is only an InputDefinitions( call
#   missing      no binding file
# Class is the "# Class: <class>" header line when a binding declares one.
#
# Usage:  perl tools/dev/demand-join.pl [--markdown] [--min-papers=N] <package-priority-regen.csv>
#
# Writes CSV (default) or a Markdown table to stdout, sorted by paper count.
# The static census is not rebuilt here and should not be rebuilt in the
# gauntlet runner either; the runner measures routes, this joins demand.

use strict;
use warnings;
use FindBin;
use File::Spec;
use Getopt::Long;

my ($markdown, $min_papers) = (0, 1);
GetOptions('markdown' => \$markdown, 'min-papers=i' => \$min_papers)
  or die "Usage: $0 [--markdown] [--min-papers=N] <package-priority-regen.csv>\n";
my $csv = shift @ARGV or die "Usage: $0 [--markdown] [--min-papers=N] <package-priority-regen.csv>\n";

my $package_dir = File::Spec->catdir($FindBin::RealBin, '..', '..', 'lib', 'LaTeXML', 'Package');

sub parse_csv_line {
  my ($line) = @_;
  my @fields;
  while ($line =~ /\G(?:"((?:[^"]|"")*)"|([^,]*))(?:,|$)/g) {
    my $f = defined $1 ? $1 : $2;
    $f =~ s/""/"/g if defined $f;
    push(@fields, $f);
    last if pos($line) >= length($line); }
  return @fields; }

sub binding_state {
  my ($pkg) = @_;
  my ($file) = grep { -f $_ } map { File::Spec->catfile($package_dir, "$pkg.$_.ltxml") } qw(sty cls);
  return ('missing', '', 0) unless $file;
  open(my $fh, '<', $file) or return ('missing', '', 0);
  my @lines = <$fh>;
  close $fh;
  my $class = '';
  my ($live_input, $code_lines) = (0, 0);
  foreach my $l (@lines) {
    $class = $1 if !$class && $l =~ /^#\s*Class:\s*(\w+)/;
    next if $l =~ /^\s*(#|$)/;
    $code_lines++;
    $live_input++ if $l =~ /^[^#]*InputDefinitions\(/; }
  my $state = 'native';
  if ($live_input) {
    # A passthrough is the InputDefinitions call plus boilerplate (package, use, 1;).
    my $other = grep { !/^\s*(package|use|1;|InputDefinitions|\}|\)|DeclareOption|ProcessOptions|RequirePackage)/ }
      grep { !/^\s*(#|$)/ } @lines;
    $state = ($other <= 1) ? 'passthrough' : 'hybrid'; }
  return ($state, $class, scalar(@lines)); }

open(my $in, '<', $csv) or die "cannot read $csv: $!\n";
my $header = <$in>;
$header =~ s/\r?\n$//;    # the census is written on Windows and may carry CRLF
my @cols = parse_csv_line($header);
my %idx = map { $cols[$_] => $_ } 0 .. $#cols;
foreach my $need (qw(package external_papers tex_origin_papers support_origin_papers priority)) {
  die "census csv lacks column '$need'\n" unless exists $idx{$need}; }

my @rows;
while (my $line = <$in>) {
  $line =~ s/\r?\n$//;
  next unless length $line;
  my @f = parse_csv_line($line);
  my $pkg = $f[$idx{package}];
  my $papers = $f[$idx{external_papers}] || 0;
  next if $papers < $min_papers;
  my ($state, $class, $lines) = binding_state($pkg);
  push(@rows, {
      package  => $pkg,
      papers   => $papers,
      tex      => $f[$idx{tex_origin_papers}] || 0,
      support  => $f[$idx{support_origin_papers}] || 0,
      priority => $f[$idx{priority}],
      state    => $state,
      class    => $class,
      lines    => $lines }); }
close $in;
@rows = sort { $b->{papers} <=> $a->{papers} || $a->{package} cmp $b->{package} } @rows;

my %by_state;
foreach my $r (@rows) { $by_state{ $r->{state} }{packages}++; $by_state{ $r->{state} }{papers} += $r->{papers}; }

if ($markdown) {
  print "| Package | Papers | From .tex | From shipped style | Census priority | Binding state | Class | Lines |\n";
  print "| :--- | ---: | ---: | ---: | :--- | :--- | :--- | ---: |\n";
  foreach my $r (@rows) {
    printf "| %s | %d | %d | %d | %s | %s | %s | %s |\n",
      @$r{qw(package papers tex support priority state)}, ($r->{class} || ''), ($r->{lines} || ''); }
  print "\nBy binding state (packages, paper-loads):";
  foreach my $s (sort keys %by_state) {
    printf " %s %d/%d;", $s, $by_state{$s}{packages}, $by_state{$s}{papers}; }
  print "\n"; }
else {
  print join(',', qw(package papers tex_origin_papers support_origin_papers census_priority binding_state class lines)), "\n";
  foreach my $r (@rows) {
    print join(',', @$r{qw(package papers tex support priority state class lines)}), "\n"; } }
