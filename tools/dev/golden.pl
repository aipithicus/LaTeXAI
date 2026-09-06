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
# Usage:  perl tools/dev/golden.pl [--force] [--check] [--lenient] t/<suite>/<case>.tex [...]
#
# Refuses to overwrite an existing golden without --force. Fails, and writes
# nothing, if the engine counted errors (status >= 2), so a golden can never be
# minted from a broken conversion.
#
# Also runs the golden lint over the digested document and refuses on:
#   - a labelref with no matching labels target anywhere in the document
#     (a \label digested inside a hook and dropped; every \ref to it dangles);
#   - an ltx:ERROR element (a construct the binding left undefined);
#   - an engine-internal \lx@... control sequence in text or a tex attribute
#     (a binding's private macro leaked into math or running text).
# Each check corresponds to a golden that was committed with the defect in it.
# --lenient reports the lint and writes anyway, for a case that exercises the
# failure on purpose. --check digests and lints without writing, for
# re-checking an existing suite.
#
# The lint is mechanical. It does not know whether the structure is right;
# read the golden against expectations written from the package source before
# committing it (docs/recipes/package-bindings.md, section 5).

use strict;
use warnings;
use FindBin;
use File::Spec;
use Getopt::Long;
use XML::LibXML;
use lib File::Spec->catdir($FindBin::RealBin, '..', '..', 'lib');
use LaTeXML::Core;
use LaTeXML::Util::Test ();    # for %CORE_OPTIONS_FOR_TESTS; import nothing

my $usage = "Usage: $0 [--force] [--check] [--lenient] <case.tex>...\n";
my ($force, $check, $lenient) = (0, 0, 0);
GetOptions('force' => \$force, 'check' => \$check, 'lenient' => \$lenient) or die $usage;
my @cases = @ARGV or die $usage;

my $LTX = 'http://dlmf.nist.gov/LaTeXML';

sub lint_golden {
  my ($xmlstring) = @_;
  my @problems;
  my $doc = eval { XML::LibXML->load_xml(string => $xmlstring) };
  return ("golden is not well-formed XML: " . ($@ || 'unknown')) unless $doc;
  my $xpc = XML::LibXML::XPathContext->new($doc);
  $xpc->registerNs(ltx => $LTX);
  # 1. Every labelref resolves to a labels attribute somewhere in the document.
  my %targets;
  foreach my $attr ($xpc->findnodes('//@labels')) {
    $targets{$_} = 1 foreach split(/\s+/, $attr->value); }
  foreach my $attr ($xpc->findnodes('//@labelref')) {
    foreach my $ref (split(/\s+/, $attr->value)) {
      push(@problems, "dangling labelref '$ref' (no element carries labels=\"$ref\")")
        unless $targets{$ref}; } }
  # 2. No ltx:ERROR element.
  foreach my $err ($xpc->findnodes('//ltx:ERROR')) {
    push(@problems, "ltx:ERROR element: " . $err->textContent); }
  # 3. No engine-internal control sequence leaked into content.
  foreach my $node ($xpc->findnodes('//text()[contains(., "\\lx@")] | //@*[contains(., "\\lx@")]')) {
    my $where = $node->isa('XML::LibXML::Attr')
      ? '@' . $node->nodeName . ' on ' . $node->ownerElement->nodeName
      : 'text in ' . $node->parentNode->nodeName;
    (my $snippet = $node->isa('XML::LibXML::Attr') ? $node->value : $node->data) =~ s/\s+/ /g;
    $snippet = substr($snippet, 0, 80) . '...' if length($snippet) > 80;
    push(@problems, "engine-internal \\lx\@ token in $where: $snippet"); }
  return @problems; }

my $failures = 0;
foreach my $tex (@cases) {
  (my $xml = $tex) =~ s/\.tex$/.xml/ or do { warn "golden.pl: $tex is not a .tex file\n"; $failures++; next; };
  if (-e $xml && !$force && !$check) {
    warn "golden.pl: $xml exists; use --force to replace it\n"; $failures++; next; }
  my $core = LaTeXML::Core->new(%LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS);
  my $dom  = eval { $core->convertFile($tex) };
  if (!$dom) {
    warn "golden.pl: $tex: conversion failed: " . ($@ || 'no document') . "\n"; $failures++; next; }
  if ($core->getStatusCode >= 2) {
    warn "golden.pl: $tex: refusing to write golden from a conversion that reported "
      . $core->getStatusMessage . "\n";
    $failures++; next; }
  my $string   = $dom->toString(1);
  my @problems = lint_golden($string);
  if (@problems) {
    my $report = join('', map { "  $_\n" } @problems);
    if ($lenient) {
      warn "golden.pl: $tex: golden lint (ignored with --lenient):\n$report"; }
    else {
      warn "golden.pl: $tex: golden lint failed:\n$report"
        . "  (fix the binding, or pass --lenient for a case that exercises this on purpose)\n";
      $failures++; next; } }
  if ($check) {
    print STDERR "golden.pl: $tex: lint " . (@problems ? 'reported' : 'clean')
      . " (" . $core->getStatusMessage . "); nothing written\n";
    next; }
  # :raw so the golden is LF on every platform; Windows perl's text layer would add CR.
  open(my $out, '>:raw:encoding(UTF-8)', $xml) or do { warn "golden.pl: cannot write $xml: $!\n"; $failures++; next; };
  print {$out} $string;
  close($out);
  print STDERR "golden.pl: wrote $xml (" . $core->getStatusMessage . ")\n"; }
exit($failures ? 1 : 0);
