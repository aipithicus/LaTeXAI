# -*- CPERL -*-
use strict;
use warnings;
use Test::More;
use LaTeXML::Core;
use XML::LibXML::XPathContext;

# Public source contracts from algorithmicx 1.2:676-785. Capture the real
# diagnostics, rather than accepting a golden produced from invalid input.
sub convert {
  my ($source) = @_;
  my $log = '';
  open(my $stream, '>', \$log) or die $!;
  local $LaTeXML::Common::Error::LOG = $stream;
  my $core = LaTeXML::Core->new(preload => ['LaTeX.pool'], verbosity => -2,
    includecomments => 0, includepathpis => 0);
  my $doc = $core->convertFile($source);
  close $stream;
  return ($doc, $core, $log);
}

my @invalid = (
  ['missing', '\\begin{algorithmic}\\algrestore{missing}\\end{algorithmic}',
    qr/Save 'missing' not defined/],
  ['duplicate', '\\begin{algorithmic}\\State a\\algstore*{same}\\end{algorithmic}'
      . '\\begin{algorithmic}\\State b\\algstore*{same}\\end{algorithmic}',
    qr/This save name 'same' is already used/],
  ['late', '\\begin{algorithmic}\\State a\\algstore*{saved}\\end{algorithmic}'
      . '\\begin{algorithmic}\\State b\\algrestore{saved}\\end{algorithmic}',
    qr/Restore might be used only at the beginning/],
  ['unrestored', '\\begin{algorithmic}\\State a\\algstore{pending}\\end{algorithmic}',
    qr/Some stored algorithms are not restored: pending/],
  ['after-store', '\\begin{algorithmic}\\State a\\algstore*{saved}\\State b\\end{algorithmic}',
    qr/The environment must be closed after store/],
  ['consumed', '\\begin{algorithmic}\\State a\\algstore{saved}\\end{algorithmic}'
      . '\\begin{algorithmic}\\algrestore{saved}\\State b\\end{algorithmic}'
      . '\\begin{algorithmic}\\algrestore{saved}\\end{algorithmic}',
    qr/Save 'saved' not defined/],
);
my ($doc, $core, $log) = convert('t/algpseudocode/continuation.tex');
is($core->getStatusCode, 0, 'valid continuation is clean') or diag($log);
my $xc = XML::LibXML::XPathContext->new($doc->getDocument);
$xc->registerNs(ltx => 'http://dlmf.nist.gov/LaTeXML');
my @numbers = map { $_->textContent } $xc->findnodes('//ltx:float//ltx:tag[not(@role)]');
is_deeply(\@numbers, ['2:', '4:', '6:'], 'frequency and remainder survive restore');
my @refs = map { $_->textContent } $xc->findnodes('//ltx:float//ltx:tag[@role="refnum"]');
is_deeply(\@refs, [1..7], 'all lines retain sequential reference numbers');
my @lines = $xc->findnodes('//ltx:float//ltx:listingline');
for my $check ([2,3], [3,3], [4,1], [5,1], [6,0]) {
  my ($line, $ems) = @$check;
  my $spaces = join('', map { $_->textContent } $lines[$line]->findnodes('./text()'));
  my $count = () = $spaces =~ /\x{2003}/g;
  is($count, $ems, 'line ' . ($line + 1) . ' keeps the saved block indentation');
}
is($xc->findvalue('count(//ltx:ERROR)'), 0, 'no continuation control leaks into XML');
for my $case (@invalid) {
  my ($name, $body, $expected) = @$case;
  subtest $name => sub {
    my ($invalid_doc, $invalid_core, $invalid_log) = convert('literal:\\documentclass{article}'
        . '\\usepackage{algpseudocode}\\begin{document}' . $body . '\\end{document}');
    ok($invalid_doc, 'invalid continuation remains recoverable');
    like($invalid_log, $expected, 'source-specified diagnostic');
    is($invalid_core->getStatusCode, 2, 'error status, not a fatal or silent success');
    unlike($invalid_log, qr/Fatal:|Error:undefined:(?!\\algrestore)/, 'no secondary fatal or undefined token');
  };
}
done_testing;
