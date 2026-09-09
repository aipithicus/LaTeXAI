#!/usr/bin/env perl
use strict;
use warnings;
use JSON::PP;
use FindBin;
use File::Spec;
use lib File::Spec->catdir($FindBin::RealBin, '..', '..', 'lib');
use lib $FindBin::RealBin;
use LaTeXML::Core;
use CaptureStrip qw(without_capture error_count);

my ($texpath, $outfile, $capture) = @ARGV;
die "usage: $0 texpath outfile.json [capture]\n" unless $outfile && @ARGV >= 2;
$capture = 1 unless defined $capture;
my %opts = (preload => [], searchpaths => [], includecomments => 0, includepathpis => 0, verbosity => -2, capture => 0+$capture);
my $result = eval {
  my $core = LaTeXML::Core->new(%opts);
  my $doc  = $core->convertFile($texpath);
  return {
    ok => ($doc ? JSON::PP::true() : JSON::PP::false()),
    stripped => $doc ? without_capture($doc) : undef,
    errors => $doc ? error_count($doc) : undef,
    status => $core->getStatusMessage,
  };
};
$result = { ok => JSON::PP::false(), error => $@ || 'undef', stripped => undef, errors => undef }
  unless $result;
open my $out, '>:raw', $outfile or die "write $outfile: $!";
print {$out} JSON::PP->new->canonical->utf8->encode($result);
close $out;
exit($result->{ok} ? 0 : 1);
