use strict;
use warnings;
use Test::More;
use LaTeXML::Core;
# Expected unsupported forms: require a diagnostic AND retained body, so a
# missing file or aborted document cannot masquerade as successful rejection.
for my $path (sort glob('t/b2-residue/*.tex')) {
 my $core=LaTeXML::Core->new(includecomments=>0,includepathpis=>0,verbosity=>-2);
 my $doc=$core->convertFile($path);
 ok($doc,"$path retains a document");
 cmp_ok($core->getStatusCode,'>=',2,"$path diagnoses unsupported input");
 my $text=$doc?$doc->documentElement->textContent:'';$text=~s/\s+/ /g;
 like($text,qr/Body retained\./,"$path preserves the surrounding content");
 unlike($text,qr/Forbidden hook/,"$path does not execute unsupported hook text");
}
done_testing;
