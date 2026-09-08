#!/usr/bin/env perl
use strict;
use warnings;
use FindBin;
use File::Spec;
use File::Basename qw(dirname);
use Cwd qw(abs_path);
use Encode qw(encode);
use Getopt::Long;
use lib File::Spec->catdir($FindBin::RealBin, '..', '..', 'lib');
use LaTeXML::Core;

# The capture driver's exact configuration, in a fresh process so repeated
# pool loading cannot add redefinition warnings to the evidence ledger.
# --golden normalizes only the same base/revision fields as t/45_capture.t.
my $golden = 0;
my $capture = 1;
my $noparse = 0;
my $autoload = 0;
GetOptions('golden' => \$golden, 'capture!' => \$capture, 'noparse' => \$noparse, 'autoload' => \$autoload)
  or die "Usage: $0 [--golden] [--no-capture] [--noparse] [--autoload] input.tex output.xml\n";
my ($input, $output) = @ARGV;
die "Usage: $0 [--golden] input.tex output.xml\n" unless defined $output && @ARGV == 2;
$input = abs_path($input) or die "Cannot resolve input\n";
my $core = LaTeXML::Core->new(
  preload => $autoload ? [] : ['LaTeX.pool'], searchpaths => [dirname($input)], capture => $capture, nomathparse => $noparse,
  includecomments => 0, includepathpis => 0, verbosity => -2);
my $document = $core->convertFile($input);
die $core->getStatusMessage . "\n" if $core->getStatusCode;
if ($golden) {
  my $ns = 'http://dlmf.nist.gov/LaTeXML/capture';
  my $dom = $document->getDocument;
  $dom->documentElement->setAttributeNS($ns, 'capture:base', 'CAPTURE_BASE');
  foreach my $engine ($dom->getElementsByTagNameNS($ns, 'engine')) {
    $engine->setAttribute(revision => 'CAPTURE_REVISION'); }
}
open(my $out, '>:raw', $output) or die "Cannot write $output: $!";
# Core::Document returns characters; LibXML::Document::toString returns bytes.
print {$out} encode('UTF-8', $document->toString(1));
close($out);
print $core->getStatusMessage . "\n";
