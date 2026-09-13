# -*- CPERL -*-
use strict;
use warnings;
use Test::More;
use LaTeXML::Core;
use XML::LibXML::XPathContext;

# Independent semantic and resource-bound checks for the containment subset.
# PGF 3.1.12 pgffor.code.tex:209-268 assigns variables locally per iteration;
# substitution must preserve one-argument boundaries and surrounding state.
my $many = join(',', 1 .. 128);
my $large = 'a' x 8192;
my $source = 'literal:\documentclass{article}\usepackage{tikz}'
  . '\def\x{outside}\def\a{outer}\begin{document}'
  . '\tikz{\foreach\x in {' . $many . '}{\node{\x};}}'
  . '\tikz{\foreach\x in {' . $many . ',129}{\node{\x};}\node{after};}'
  . '\tikz{\foreach\x in {12,34}{\node{$\frac\x2$};}\node{\x};}'
  . '\tikz{\foreach\a/\b/\c/\d/\e/\f/\g/\h in {1/2/3/4/5/6/7/8}{\node{\a\h};}}'
  . '\tikz{\foreach\a/\b/\c/\d/\e/\f/\g/\h/\i in {1/2/3/4/5/6/7/8/9}{\node{\a};}}'
  . '\tikz{\foreach\x in {1,2}{\node{' . $large . '\x};}'
  . '\foreach\x in {3,4}{\node{' . $large . '\x};}\node{after};}'
  . '\tikz{\foreach\x in {7,8}{\node{\x};}}'
  . '\tikz{\foreach\x in {1,2}\node{\x}}'
  . '\tikz{\foreach\x in {\bf}{\node{\x bold};}\node{plain};}'
  . '\tikz{\foreach\x in {\x}{\node{\x};}}'
  . '\end{document}';
my $log = '';
open(my $stream, '>', \$log) or die $!;
local $LaTeXML::Common::Error::LOG = $stream;
my $core = LaTeXML::Core->new(preload => ['LaTeX.pool'], verbosity => -2,
  includecomments => 0, includepathpis => 0);
my $doc = $core->convertFile($source);
close $stream;
ok($doc, 'bounded and unsupported loops remain recoverable');
unlike($log, qr/(?:Error|Fatal):/, 'no engine errors') or diag($log);
my $xc = XML::LibXML::XPathContext->new($doc->getDocument);
$xc->registerNs(ltx => 'http://dlmf.nist.gov/LaTeXML');
my @pictures = $xc->findnodes('//ltx:picture');
is(scalar(@pictures), 10, 'all picture envelopes survive');
sub labels {
  my ($i) = @_;
  return [map { $_->textContent } $xc->findnodes('./ltx:g', $pictures[$i])];
}
is_deeply(labels(0), [1 .. 128], '128 items expand in order');
is_deeply(labels(1), ['outside', 'after'], '129 items retain once with no partial expansion');
my @math = $xc->findnodes('.//ltx:Math', $pictures[2]);
is(scalar(@math), 2, 'two fraction labels');
my @numerators = map { $xc->findvalue('./ltx:XMath/ltx:XMApp/*[2]', $_) } @math;
is_deeply(\@numerators, ['12', '34'], 'multi-token values remain single TeX arguments');
my @operators = map { $xc->findvalue('./ltx:XMath/ltx:XMApp/*[1]/@role', $_) } @math;
is_deeply(\@operators, ['FRACOP', 'FRACOP'], 'both labels parse as fractions');
is((labels(2))->[-1], 'outside', 'loop variables do not escape');
is_deeply(labels(3), ['18'], 'eight variables supported');
is_deeply(labels(4), ['outer'], 'nine variables retain once');
is_deeply(labels(5), [$large . '1', $large . '2', $large . 'outside', 'after'],
  'picture budget accumulates across loops and rejects the whole excess loop');
is_deeply(labels(6), ['7', '8'], 'budget resets for the next picture');
is_deeply(labels(7), ['outside'], 'unterminated body retains its label once');
is($xc->findvalue('./ltx:g[1]/ltx:text[@font="bold"]', $pictures[8]), 'bold',
  'a declaration in a value applies to the following label text');
is($xc->findvalue('count(./ltx:g[2]/ltx:text[@font])', $pictures[8]), 0,
  'a label-local declaration does not affect the next label');
is_deeply(labels(9), ['outside'], 'self-referential values retain once without recursion');
for my $reason ('item limit', 'variable limit', 'picture token limit', 'unterminated body', 'dependent values') {
  like($log, qr/Foreach harvest retained once: \Q$reason\E/, "$reason is diagnosed");
}
my $warnings = () = $log =~ /Warning:unsupported:tikz-foreach/g;
is($warnings, 5, 'each rejected loop emits one diagnostic');
like($pictures[2]->getAttribute('tex'), qr/\\foreach\\x in \{12,34\}/,
  'picture reversion retains the original loop');
unlike($pictures[2]->getAttribute('tex'), qr/frac\{12\}/,
  'generated iteration text does not replace raw picture source');
done_testing;
