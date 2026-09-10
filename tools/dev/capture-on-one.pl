#!/usr/bin/env perl
use strict;
use warnings;
use FindBin;
use File::Spec;
use lib File::Spec->catdir($FindBin::RealBin, '..', '..', 'lib');
use lib $FindBin::RealBin;
use CaptureAudit qw(read_json write_json json_bytes);
use CaptureStrip qw(without_capture error_count);
use LaTeXML::Core;

my ($request_path, $outfile) = @ARGV;
die "usage: $0 request.json result.json\n" unless @ARGV == 2;
open STDOUT, '>:raw', "$outfile.stdout" or die $!;
open STDERR, '>:raw', "$outfile.stderr" or die $!;
my $request = read_json($request_path);
die "Invalid capture audit request\n" unless ref($request) eq 'HASH'
  && ($request->{format} || '') eq $CaptureAudit::FORMAT
  && defined($request->{texpath}) && ref($request->{options}) eq 'HASH';
my $options = JSON::PP->new->utf8->decode(json_bytes($request->{options}));
my $result = eval {
  my $core = LaTeXML::Core->new(%$options);
  my $doc = $core->convertFile($request->{texpath});
  +{ ok => $doc ? JSON::PP::true : JSON::PP::false,
    raw => $doc ? $doc->toString(1) : undef,
    stripped => $doc ? without_capture($doc) : undef,
    error_nodes => $doc ? error_count($doc) : undef,
    status_code => $core->getStatusCode, status_message => $core->getStatusMessage };
};
$result ||= { ok => JSON::PP::false, error => $@ || 'No result' };
$result->{format} = $CaptureAudit::FORMAT;
$result->{options} = $request->{options};
write_json($outfile, $result);
# Conversion failures are structured results; process failures are separate.
exit 0;
