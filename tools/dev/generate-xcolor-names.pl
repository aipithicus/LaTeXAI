#!/usr/bin/env perl
# Compile only the two pinned xcolor RGB sets; reject unrecognized source code.
use strict;
use warnings;
use FindBin;
use File::Spec;
use Digest::SHA qw(sha256_hex);

my $check = @ARGV && $ARGV[0] eq '--check' ? shift @ARGV : undef;
die "Usage: $0 [--check]\n" if @ARGV;
my $root = File::Spec->rel2abs("$FindBin::Bin/../..");
my $output = "$root/lib/LaTeXML/Package/XColorNames.pm";
my $text = "# Generated from xcolor 3.02 (2024-09-29), under LPPL 1.3c.\n"
  . "# Copyright (C) 2003-2021 Uwe Kern; 2021-2024 The LaTeX Project.\n"
  . "# Source: lib-ctan/xcolor/tex/latex/xcolor/{svgnam,x11nam}.def\n"
  . "# Regenerate: perl tools/dev/generate-xcolor-names.pl\n"
  . "# Owned by xcolor.sty.ltxml; decimal strings and declaration order are retained.\n"
  . "package LaTeXML::Package::XColorNames;\nuse strict;\nuse warnings;\nmy \$tables = {\n";
my $count = 0;
for my $file (qw(svgnam.def x11nam.def)) {
  open(my $in, '<:raw', "$root/lib-ctan/xcolor/tex/latex/xcolor/$file") or die "$file: $!";
  my $raw = do { local $/; <$in> }; close($in);
  my $source = $raw;
  $source =~ s/%[^\r\n]*[\r\n]*//g;
  my ($set) = $source =~ /\A\s*\\ProvidesFile\{\Q$file\E\}\s*
    \[2024\/09\/29\ v3\.02\ Predefined\ colors\ according\ to\ [^\]]+\]\s*
    \\def\\colornameprefix\{XC\@\}\s*
    \\preparecolorset\{rgb\}\{\}\{\}\{([^{}]*)\}\s*\\endinput\s*\z/x;
  die "Unrecognized xcolor source structure in $file\n" unless defined $set;
  my $hash = sha256_hex($raw);
  $text .= "  '$file' => { sha256 => '$hash', colors => [\n";
  my %seen;
  for my $row (split(/;/, $set)) {
    $row =~ s/^\s+|\s+$//g;
    my ($name, @rgb) = split(/,/, $row, -1);
    die "Invalid color row in $file: $row\n" unless $name =~ /^[A-Za-z][A-Za-z0-9]*$/
      && !$seen{$name}++ && @rgb == 3
      && !grep { !/^(?:\d+(?:\.\d*)?|\.\d+)$/ || $_ < 0 || $_ > 1 } @rgb;
    $text .= "    ['" . join("', '", $name, @rgb) . "'],\n";
    $count++;
  }
  $text .= "  ] },\n";
}
$text .= "};\nsub data { return \$tables; }\n1;\n";
if ($check) {
  open(my $in, '<:raw', $output) or die "$output: $!";
  my $old = do { local $/; <$in> }; close($in);
  die "Generated xcolor data is stale; rerun $0\n" unless $old eq $text;
}
else {
  open(my $out, '>:raw', $output) or die "$output: $!";
  print {$out} $text; close($out) or die "$output: $!";
}
print(($check ? 'Verified' : 'Generated') . " $count colors in two xcolor tables\n");
