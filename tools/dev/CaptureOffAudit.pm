package CaptureOffAudit;
use strict;
use warnings;
use Cwd qw(abs_path);
use Digest::SHA qw(sha256_hex);
use Encode qw(encode);
use File::Path qw(make_path);
use File::Spec;
use File::Temp qw(tempfile);
use JSON::PP;
use LaTeXML::Util::Test ();
use CaptureStrip qw(without_capture error_count);

my $on_script = $INC{'CaptureOffAudit.pm'} || '';
$on_script =~ s/CaptureOffAudit\.pm$/capture-on-one.pl/;

# Load only in the primary prove process with -MCaptureOffAudit.  The real
# driver still selects fixtures and conversion options; capture their raw
# serialization before Util::Test canonicalizes it for golden comparison.
# LATEXAI_CAPTURE_OFF_BASELINE selects the baseline directory.  Set
# LATEXAI_CAPTURE_OFF_COMPARE=1 to compare instead of creating that baseline.
# LATEXAI_CAPTURE_ON_AUDIT=1 converts each capture-off fixture again with
# capture on, strips capture metadata, and compares the ltx tree and the
# ltx:ERROR count against the capture-off serialization.
my $root = $ENV{LATEXAI_CAPTURE_OFF_BASELINE}
  or die "CaptureOffAudit requires LATEXAI_CAPTURE_OFF_BASELINE\n";
my $compare = $ENV{LATEXAI_CAPTURE_OFF_COMPARE};
my $capture_on_audit = $ENV{LATEXAI_CAPTURE_ON_AUDIT};
my $json = JSON::PP->new->canonical;
my $driver = $0;
$driver =~ s{.*[\\/]}{};
my $directory = File::Spec->catdir($root, $driver);
make_path($directory) unless -d $directory;
my %seen;
my $capture_on_count = 0;
my @capture_on_diffs;
my $original = \&LaTeXML::Util::Test::convert_texfile_as_test;
{
  no warnings 'redefine';
  *LaTeXML::Util::Test::convert_texfile_as_test = sub {
    my %options = @_;
    my $document = $original->(@_);
    return $document unless $document;
    return $document if $options{core_options} && $options{core_options}{capture};
    my $identity = $json->encode({
      source => abs_path($options{texpath}),
      name => $options{name},
      options => $options{core_options} || \%LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS,
    });
    my $key = sha256_hex(encode('UTF-8', $identity));
    $seen{$key} = 1;
    my $path = File::Spec->catfile($directory, "$key.xml");
    my $bytes = encode('UTF-8', $document->toString(1));
    if ($compare) {
      if (-f $path) {
        open(my $in, '<:raw', $path) or die "Cannot read $path: $!";
        local $/;
        my $expected = <$in>;
        close($in);
        die "Capture-off raw serialization changed: $options{texpath} ($options{name})\n"
          unless $bytes eq $expected;
      }
      else {
        warn "CaptureOffAudit: new fixture outside baseline: $options{texpath}\n";
      }
    }
    else {
      open(my $out, '>:raw', $path) or die "Cannot write $path: $!";
      print {$out} $bytes;
      close($out);
      open(my $meta, '>:raw', File::Spec->catfile($directory, "$key.json")) or die $!;
      print {$meta} encode('UTF-8', $identity);
      close($meta);
    }
    if ($capture_on_audit) {
      $capture_on_count++;
      my %core_options = $options{core_options}
        ? %{ $options{core_options} }
        : %LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS;
      $core_options{capture} = 1;
      my $reason = _capture_on_compare($document, \%core_options, $options{texpath});
      if ($reason) {
        push @capture_on_diffs, {
          source => abs_path($options{texpath}),
          name => $options{name},
          reason => $reason,
        }; }
    }
    return $document;
  };
}

sub _capture_on_compare {
  my ($off_document, $core_options, $texpath) = @_;
  my ($outfh, $outfile) = tempfile('capon-out-XXXXXX', SUFFIX => '.json', UNLINK => 0);
  close $outfh;
  my @cmd = ($^X, '-I', 'lib', '-I', 'tools/dev', $on_script, $texpath, $outfile);
  my $status = system(@cmd);
  my $raw;
  if (-f $outfile) {
    open my $in, '<:raw', $outfile;
    local $/;
    $raw = <$in>;
    close $in; }
  unlink $outfile;
  return 'capture-on helper produced no output (status ' . ($status >> 8) . ')' unless defined $raw && length $raw;
  my $result = eval { JSON::PP->new->utf8->decode($raw) };
  return "capture-on helper returned invalid JSON: $@" if $@ || !$result;
  return 'capture-on conversion failed: ' . ($result->{status} || $result->{error} || 'undef')
    unless $result->{ok};
  my $off_xml = without_capture($off_document);
  my $on_xml  = $result->{stripped};
  my $off_err = error_count($off_document);
  my $on_err  = $result->{errors};
  if (!defined $off_xml || !defined $on_xml || $off_xml ne $on_xml) {
    return 'stripped ltx tree differs'; }
  return "ltx:ERROR count $off_err vs $on_err" if $off_err != $on_err;
  return; }

END {
  if ($compare && -d $directory) {
    opendir(my $dir, $directory) or die $!;
    my @missing = grep { /\.xml$/ && !$seen{substr($_, 0, -4)} } readdir($dir);
    closedir($dir);
    if (@missing) {
      warn "CaptureOffAudit: $driver omitted " . scalar(@missing) . " baseline conversions\n";
      $? = 1;
    }
  }
  if ($capture_on_audit) {
    warn "CaptureOnAudit: $driver audited $capture_on_count conversions, "
      . scalar(@capture_on_diffs) . " differences\n";
    my $report = File::Spec->catfile($directory, 'capture-on-audit.json');
    open(my $out, '>:raw', $report) or die "Cannot write $report: $!";
    print {$out} encode('UTF-8', $json->pretty->encode({
      driver => $driver,
      audited => $capture_on_count,
      differences => \@capture_on_diffs,
    }));
    close($out);
    $? = 1 if @capture_on_diffs;
  }
}

1;
