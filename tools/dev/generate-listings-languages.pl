#!/usr/bin/env perl
# Compile the pinned listings 1.11b tables through the binding's own TeX reader.
# Run from the checkout with the repository Perl: perl -I lib tools/dev/generate-listings-languages.pl [--check]
use strict;
use warnings;
use FindBin;
use File::Spec;
use Digest::SHA qw(sha256_hex);
use Data::Dumper;
use Encode qw(decode);
use LaTeXML::Core;
use LaTeXML::Package;
use LaTeXML::Core::SourceRegistry;
use LaTeXML::Package::ListingsLanguages;

my $check = @ARGV && $ARGV[0] eq '--check' ? shift @ARGV : undef;
die "Usage: $0 [--check]\n" if @ARGV;
my $root = File::Spec->rel2abs("$FindBin::Bin/../..");
my $output = "$root/lib/LaTeXML/Package/listings.languages.pl";
my $core = LaTeXML::Core->new(verbosity => -2, includestyles => 1, capture => 1);
my %tables;
$core->withState(sub {
    my ($state) = @_;
    AssignValue(SOURCE_REGISTRY => LaTeXML::Core::SourceRegistry->new(), 'global');
    $core->initializeState('TeX.pool', 'LaTeX.pool');
    InputDefinitions('listings', type => 'sty');
    for my $number (1 .. 3) {
      my $file = "lstlang$number.sty";
      my $path = "$root/lib-ctan/listings/tex/latex/listings/$file";
      open(my $in, '<:raw', $path) or die "$path: $!";
      my $raw = do { local $/; <$in> }; close($in);
      my %catcodes = map { $_ => $state->lookupCatcode($_) } split(//, decode('UTF-8', $raw));
      my @definitions;
      my $assign = \&LaTeXML::Core::State::assignValue;
      {
        no warnings 'redefine';
        local *LaTeXML::Core::State::assignValue = sub {
          my ($s, $key, $value, @rest) = @_;
          if ($key =~ /^LST\@LANGUAGE\@/) {
            push(@definitions, [$key, LaTeXML::Package::ListingsLanguages::freeze($value, $file)]); }
          return $assign->(@_); };
        # Explicit raw input is independent of the generated runtime path.
        InputDefinitions($path, noltxml => 1);
      }
      die "No definitions in $file\n" unless @definitions;
      $tables{$file} = { sha256 => sha256_hex($raw), catcodes => \%catcodes, definitions => \@definitions };
    }
});
die $core->getStatusMessage if $core->getStatusCode >= 2;
my $text = "# Generated from listings 1.11b (2025-11-14), distributed under LPPL 1.3c.\n"
  . "# Source: lib-ctan/listings/tex/latex/listings/lstlang{1,2,3}.sty\n"
  . "# Regenerate: perl -I lib tools/dev/generate-listings-languages.pl\n"
  . "# Token catcodes and capture coordinates are minted by the native Mouth.\n"
  . "use utf8;\n"
  . dump_data(\%tables, 0) . ";\n";
if ($check) {
  open(my $in, '<:raw:encoding(UTF-8)', $output) or die "$output: $!";
  my $old = do { local $/; <$in> }; close($in);
  die "Generated listings data is stale; rerun $0\n" unless $text eq $old;
}
else {
  open(my $out, '>:raw:encoding(UTF-8)', $output) or die "$output: $!";
  print {$out} $text; close($out) or die "$output: $!";
}
my $count = 0; $count += scalar(@{$_->{definitions}}) for values %tables;
print(($check ? 'Verified' : 'Generated') . " $count language definitions in three tables\n");

# Keep short token runs on one line so the generated artifact is reviewable.
sub dump_data {
  my ($value, $level) = @_;
  return Data::Dumper->new([$value])->Terse(1)->Indent(0)->Useqq(0)->Dump unless ref($value);
  my $indent = '  ' x $level;
  if (ref($value) eq 'ARRAY') {
    return '[' . join(', ', map { dump_data($_, 0) } @$value) . ']' unless grep { ref($_) } @$value;
    return "[\n" . join(",\n", map { $indent . '  ' . dump_data($_, $level + 1) } @$value) . "\n$indent]";
  }
  die 'Unsupported generated data type' unless ref($value) eq 'HASH';
  return "{\n" . join(",\n", map { $indent . '  ' . dump_data($_, 0) . ' => '
      . dump_data($value->{$_}, $level + 1) } sort keys %$value) . "\n$indent}";
}
