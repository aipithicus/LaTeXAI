# -*- CPERL -*-
# The kpsewhich shim, through the engine's own pathname_kpsewhich.
# LATEXML_KPSEWHICH is set in BEGIN so Pathname.pm's load-time which() sees it.
use strict;
use warnings;
use File::Spec;
use FindBin;

BEGIN {
  my $root = File::Spec->catdir($FindBin::Bin, '..');
  my $cmd  = File::Spec->rel2abs(File::Spec->catfile($root, 'tools', 'dev', 'kpsewhich.cmd'));
  $ENV{LATEXML_KPSEWHICH} = $cmd;
}

use Test::More;
use LaTeXML::Util::Pathname;

plan tests => 6;

my $found = pathname_kpsewhich('ifthen.sty');
ok($found, 'pathname_kpsewhich finds ifthen.sty');
like($found, qr{/ifthen/tex/latex/base/ifthen\.sty$}i, 'path is the lib-ctan entry');
ok(-f $found, 'the path exists');
ok($LaTeXML::Util::Pathname::kpse_cache->{'ifthen.sty'},
  'startup cache was populated (not the per-file fallback)');

my $missing = pathname_kpsewhich('latexai-no-such-file.sty');
ok(!defined $missing, 'unknown name returns undef');

# Empty-but-defined cache forces the Win32::ShellQuote / open '-|' fallback.
%{ $LaTeXML::Util::Pathname::kpse_cache } = ();
my $via_fallback = pathname_kpsewhich('ifthen.sty');
ok($via_fallback && -f $via_fallback, 'fallback process finds ifthen.sty');
