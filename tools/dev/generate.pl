#!/usr/bin/env perl
# tools/dev/generate.pl
#
# Produce the two generated modules the engine needs, into lib/ beside their
# sources, so that `perl -I lib` is the whole include path for development:
#
#   lib/LaTeXML/MathGrammar.pm   compiled from lib/LaTeXML/MathGrammar (Parse::RecDescent)
#   lib/LaTeXML/Version.pm       stamped from lib/LaTeXML/Version.in with the git revision
#
# Both outputs are gitignored. This is the development-loop counterpart of the
# rules Makefile.PL adds for `make`; it does not touch blib/ or the Makefile,
# which remain the path to an installable distribution.
#
# Usage:  perl tools/dev/generate.pl [--force] [--quiet]
#
# The grammar is recompiled only when its source is newer than the output
# (or --force). The version module is rewritten only when the revision changed.

use strict;
use warnings;
use FindBin;
use File::Spec;
use File::Copy qw(move);
use File::Temp qw(tempdir);
use Cwd qw(abs_path getcwd);

my $force = grep { $_ eq '--force' } @ARGV;
my $quiet = grep { $_ eq '--quiet' } @ARGV;

my $root = abs_path(File::Spec->catdir($FindBin::RealBin, '..', '..'));
chdir($root) or die "generate.pl: cannot enter $root: $!\n";

my $grammar_src = File::Spec->catfile('lib', 'LaTeXML', 'MathGrammar');
my $grammar_out = File::Spec->catfile('lib', 'LaTeXML', 'MathGrammar.pm');
my $version_in  = File::Spec->catfile('lib', 'LaTeXML', 'Version.in');
my $version_out = File::Spec->catfile('lib', 'LaTeXML', 'Version.pm');

sub say_ { print STDERR "generate.pl: @_\n" unless $quiet; }

#----------------------------------------------------------------------
# 1. MathGrammar.pm
#----------------------------------------------------------------------
-f $grammar_src or die "generate.pl: grammar source $grammar_src not found\n";
my $grammar_stale = $force || !-e $grammar_out
  || (stat($grammar_src))[9] > (stat($grammar_out))[9];

if ($grammar_stale) {
  say_("compiling $grammar_src -> $grammar_out");
  # Parse::RecDescent's precompiler writes <LastNameComponent>.pm into the
  # current directory, so run it inside a scratch directory and move the result.
  my $abs_src = abs_path($grammar_src);
  my $scratch = tempdir('latexai-grammar-XXXXXX', TMPDIR => 1, CLEANUP => 1);
  my $here    = getcwd();
  chdir($scratch) or die "generate.pl: cannot enter $scratch: $!\n";
  my @cmd = ($^X, '-MParse::RecDescent', '-', $abs_src, 'LaTeXML::MathGrammar', 'Parse::RecDescent');
  my $status = system(@cmd);
  if ($status != 0 || !-e 'MathGrammar.pm') {
    say_("precompile with explicit parent class failed; retrying upstream fallback form");
    $status = system($^X, '-MParse::RecDescent', '-', $abs_src, 'LaTeXML::MathGrammar'); }
  chdir($here) or die "generate.pl: cannot return to $here: $!\n";
  my $produced = File::Spec->catfile($scratch, 'MathGrammar.pm');
  ($status == 0 && -s $produced)
    or die "generate.pl: Parse::RecDescent did not produce MathGrammar.pm (exit " . ($status >> 8) . ")\n";
  move($produced, $grammar_out) or die "generate.pl: cannot move grammar into place: $!\n";
  say_("wrote $grammar_out (" . (-s $grammar_out) . " bytes)"); }
else {
  say_("$grammar_out is current"); }

#----------------------------------------------------------------------
# 2. Version.pm
#----------------------------------------------------------------------
-f $version_in or die "generate.pl: version template $version_in not found\n";
my $revision = 'unknown';
if (-e '.git') {
  my $git = `git log --max-count=1 --abbrev-commit --pretty=%h 2>&1`;
  chomp($git);
  $revision = $git if $? == 0 && $git =~ /^[0-9a-f]{7,}$/; }

open(my $in, '<', $version_in) or die "generate.pl: cannot read $version_in: $!\n";
my $stamped = do { local $/; <$in> };
close($in);
$stamped =~ s/__REVISION__/$revision/g;

my $current = '';
if (-e $version_out) {
  open(my $cur, '<', $version_out) or die "generate.pl: cannot read $version_out: $!\n";
  $current = do { local $/; <$cur> };
  close($cur); }

if ($force || $current ne $stamped) {
  open(my $out, '>', $version_out) or die "generate.pl: cannot write $version_out: $!\n";
  print {$out} $stamped;
  close($out);
  say_("wrote $version_out (revision $revision)"); }
else {
  say_("$version_out is current (revision $revision)"); }

exit 0;
