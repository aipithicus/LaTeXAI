#!/usr/bin/env perl
# tools/dev/kpsewhich.pl — LATEXML_KPSEWHICH target, invoked by scripts/kpsewhich.cmd.
# Answers from lib-ctan/ls-R
# only. No banner, no warnings on stdout.
use strict;
use warnings;
use FindBin;
use File::Spec;

my $lib_ctan = File::Spec->rel2abs(File::Spec->catdir($FindBin::RealBin, '..', '..', 'lib-ctan'));
$lib_ctan =~ s{\\}{/}g;

if (grep { $_ eq '--expand-var' } @ARGV) {
  print "$lib_ctan\n";
  print "$lib_ctan/\n";
  exit 0; }

my $lsr = "$lib_ctan/ls-R";
exit 1 unless -f $lsr;

my %by_name;
{
  open(my $fh, '<:raw', $lsr) or exit 1;
  my $subdir = '';
  while (defined(my $line = <$fh>)) {
    $line =~ s/\n\z//;
    $line =~ s/\r\z//;
    next if $line eq '' || substr($line, 0, 1) eq '%';
    if (substr($line, -1) eq ':') {
      $subdir = substr($line, 0, -1);
      $subdir =~ s|^\./||;
      next; }
    $by_name{$line} = "$lib_ctan/$subdir/$line"; }
  close $fh; }

foreach my $arg (@ARGV) {
  next if $arg =~ /^-/;
  $arg =~ s{.*[/\\]}{};
  if (my $path = $by_name{$arg}) {
    print "$path\n";
    exit 0; } }
exit 1;
