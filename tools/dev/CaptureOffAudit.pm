package CaptureOffAudit;
use strict;
use warnings;
use Cwd qw(abs_path);
use Digest::SHA qw(sha256_hex);
use Encode qw(encode);
use File::Path qw(make_path);
use File::Spec;
use JSON::PP;
use LaTeXML::Util::Test ();

# Load only in the primary prove process with -MCaptureOffAudit.  The real
# driver still selects fixtures and conversion options; capture their raw
# serialization before Util::Test canonicalizes it for golden comparison.
# LATEXAI_CAPTURE_OFF_BASELINE selects the baseline directory.  Set
# LATEXAI_CAPTURE_OFF_COMPARE=1 to compare instead of creating that baseline.
my $root = $ENV{LATEXAI_CAPTURE_OFF_BASELINE}
  or die "CaptureOffAudit requires LATEXAI_CAPTURE_OFF_BASELINE\n";
my $compare = $ENV{LATEXAI_CAPTURE_OFF_COMPARE};
my $json = JSON::PP->new->canonical;
my $driver = $0;
$driver =~ s{.*[\\/]}{};
my $directory = File::Spec->catdir($root, $driver);
make_path($directory) unless -d $directory;
my %seen;
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
    return $document;
  };
}

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
}

1;
