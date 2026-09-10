# -*- CPERL -*-
# The kpsewhich shim, through the engine's own pathname_kpsewhich.
# LATEXML_KPSEWHICH is set in BEGIN so Pathname.pm's load-time which() sees it.
use strict;
use warnings;
use File::Spec;
use File::Path qw(make_path);
use FindBin;

BEGIN {
  my $root = File::Spec->catdir($FindBin::Bin, '..');
  my $cmd  = File::Spec->rel2abs(File::Spec->catfile($root, 'scripts', 'kpsewhich.cmd'));
  $ENV{LATEXML_KPSEWHICH} = $cmd;
}

use Test::More;
use LaTeXML::Util::Pathname;

plan tests => 8;

my $found = pathname_kpsewhich('ifthen.sty');
ok($found, 'pathname_kpsewhich finds ifthen.sty');
like($found, qr{/ifthen/tex/latex/base/ifthen\.sty$}i, 'path is the lib-ctan entry');
ok(-f $found, 'the path exists');
ok($LaTeXML::Util::Pathname::kpse_cache->{'ifthen.sty'},
  'startup cache was populated (not the per-file fallback)');

my $missing = pathname_kpsewhich('latexai-no-such-file.sty');
ok(!defined $missing, 'unknown name returns undef');

# Empty-but-defined cache forces the Win32::ShellQuote / open '-|' fallback.
# Aliases set CACHE_ONLY; this case is the upstream MiKTeX path, so clear it.
{
  local $ENV{LATEXML_KPSEWHICH_CACHE_ONLY};
  delete $ENV{LATEXML_KPSEWHICH_CACHE_ONLY};
  my %saved = %{ $LaTeXML::Util::Pathname::kpse_cache };
  %{ $LaTeXML::Util::Pathname::kpse_cache } = ();
  my $via_fallback = pathname_kpsewhich('ifthen.sty');
  ok($via_fallback && -f $via_fallback, 'fallback process finds ifthen.sty');
  %{ $LaTeXML::Util::Pathname::kpse_cache } = %saved; }

# CACHE_ONLY: a miss must not spawn. Point kpsewhich at a cmd that stamps a file.
{
  my $dir = File::Spec->catdir($FindBin::Bin, '..', 'temp', 't', 'kpsewhich');
  make_path($dir);
  my $stamp = File::Spec->catfile($dir, 'spawned');
  unlink $stamp if -e $stamp;
  my $cmd = File::Spec->catfile($dir, 'count.cmd');
  open(my $fh, '>:raw', $cmd) or die "cannot write $cmd: $!";
  print $fh "\@echo off\r\necho spawned>>\"$stamp\"\r\nexit /b 1\r\n";
  close $fh;
  local $ENV{LATEXML_KPSEWHICH_CACHE_ONLY} = '1';
  local $LaTeXML::Util::Pathname::kpsewhich = $cmd;
  pathname_kpsewhich('latexai-no-such-file.sty');
  ok(!-e $stamp, 'CACHE_ONLY miss does not spawn kpsewhich');
  ok($LaTeXML::Util::Pathname::kpse_cache->{'ifthen.sty'}
      && pathname_kpsewhich('ifthen.sty'),
    'CACHE_ONLY hit still comes from the ls-R cache'); }
