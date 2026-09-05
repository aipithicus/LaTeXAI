#!/usr/bin/env perl
# tools/dev/golden.pl
#
# Write the golden <case>.xml for one or more fixtures using exactly the core
# configuration the shared test driver (LaTeXML::Util::Test) digests with, so
# that the golden compares equal to what `prove` will produce.
#
# The CLI cannot do this: `latexml` always emits a <?latexml searchpaths=...?>
# processing instruction that the driver suppresses (includepathpis => 0), so
# a golden written with `lxml` fails at line 1.
#
# Usage:  perl tools/dev/golden.pl [--force] t/<suite>/<case>.tex [...]
#
# Refuses to overwrite an existing golden without --force. Fails, and writes
# nothing, if the engine counted errors (status >= 2), so a golden can never be
# minted from a broken conversion. Read the golden before committing it.

use strict;
use warnings;
use FindBin;
use File::Spec;
use Getopt::Long;
use lib File::Spec->catdir($FindBin::RealBin, '..', '..', 'lib');
use LaTeXML::Core;
use LaTeXML::Util::Test ();    # for %CORE_OPTIONS_FOR_TESTS; import nothing

my $force = 0;
GetOptions('force' => \$force) or die "Usage: $0 [--force] <case.tex>...\n";
my @cases = @ARGV or die "Usage: $0 [--force] <case.tex>...\n";

my $failures = 0;
foreach my $tex (@cases) {
  (my $xml = $tex) =~ s/\.tex$/.xml/ or do { warn "golden.pl: $tex is not a .tex file\n"; $failures++; next; };
  if (-e $xml && !$force) {
    warn "golden.pl: $xml exists; use --force to replace it\n"; $failures++; next; }
  my $core = LaTeXML::Core->new(%LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS);
  my $dom  = eval { $core->convertFile($tex) };
  if (!$dom) {
    warn "golden.pl: $tex: conversion failed: " . ($@ || 'no document') . "\n"; $failures++; next; }
  if ($core->getStatusCode >= 2) {
    warn "golden.pl: $tex: refusing to write golden from a conversion that reported "
      . $core->getStatusMessage . "\n";
    $failures++; next; }
  open(my $out, '>:encoding(UTF-8)', $xml) or do { warn "golden.pl: cannot write $xml: $!\n"; $failures++; next; };
  print {$out} $dom->toString(1);
  close($out);
  print STDERR "golden.pl: wrote $xml (" . $core->getStatusMessage . ")\n"; }
exit($failures ? 1 : 0);
