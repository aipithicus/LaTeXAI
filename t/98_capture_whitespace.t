use strict;
use warnings;
use Test::More;
use FindBin;
use File::Spec;
use XML::LibXML;
use lib File::Spec->catdir($FindBin::Bin, '..', 'tools', 'dev');
use CaptureAudit qw(file_hash);
use CaptureStrip qw(without_capture);
use CaptureWhitespace qw(load_whitespace_model normalize_formatting);

chdir File::Spec->catdir($FindBin::Bin, '..') or die $!;
my $file = 'lib/LaTeXML/resources/RelaxNG/LaTeXML.model';
my $policy = load_whitespace_model($file, file_hash($file));
my $ns = 'http://dlmf.nist.gov/LaTeXML';
my $cap = "$ns/capture";
sub xml { XML::LibXML->load_xml(string => $_[0], keep_blanks => 1, load_ext_dtd => 0, no_network => 1); }
sub document { xml(qq{<document xmlns="$ns" xmlns:c="$cap">$_[0]</document>}); }
sub normalized { without_capture(normalize_formatting($_[0], $policy)->{document}); }

ok(!eval { load_whitespace_model($file, '0' x 64); 1 }, 'wrong model pin fails closed');
ok(!eval { load_whitespace_model($file, undef); 1 }, 'missing model pin fails closed');
is($policy->{contract}{schema}, 'latexai/model-whitespace/1', 'normalization contract is named');
ok(keys(%{$policy->{contract}{implementation}}) > 1, 'loaded model code and normalizer are pinned');

my $plain = document('<section><para><p><text>a</text> <text>b</text></p></para></section><!--keep-->');
my $pretty = document("\n  <section>\n    <para>\n      <p><text>a</text> <text>b</text></p>\n    </para>\n  </section><!--keep-->\n  <c:ledger/>\n");
my $before = $pretty->toString(0);
isnt(without_capture($plain), without_capture($pretty), 'default capture strip still retains every whitespace difference');
is(normalized($plain), normalized($pretty), 'declared element-only formatting normalizes symmetrically');
is($pretty->toString(0), $before, 'normalization preserves the input DOM');
my $result = normalize_formatting($pretty, $policy);
ok($result->{record}{removed_nodes} > 0, 'removed formatting is measured');
ok($result->{record}{by_element}{'ltx:document'}{bytes} > 0, 'removals identify the owning element');
is(normalized($result->{document}), normalized($pretty), 'normalization is idempotent');
is(normalize_formatting($result->{document}, $policy)->{record}{removed_nodes}, 0, 'second normalization removes nothing');

for my $case (
  ['prose space', '<p><text>a</text> <text>b</text></p>', '<p><text>a</text><text>b</text></p>'],
  ['mixed newlines', "<p>a\n b</p>", '<p>a b</p>'],
  ['text only whitespace', "<text> \n\t</text>", '<text/>'],
  ['verbatim', "<verbatim> \n\t</verbatim>", '<verbatim/>'],
  ['literal subtree', "<verbatim><section> \n</section></verbatim>", '<verbatim><section/></verbatim>'],
  ['foreign subtree', '<foreign xmlns="urn:foreign"><section xmlns="'.$ns.'"> </section></foreign>', '<foreign xmlns="urn:foreign"><section xmlns="'.$ns.'"/></foreign>'],
  ['unknown subtree', '<custom><section> </section></custom>', '<custom><section/></custom>'],
  ['unmodeled mixed text', '<section>text <para/> </section>', '<section>text <para/></section>'],
  ['unmodeled inline children', '<para><text>a</text> <text>b</text></para>', '<para><text>a</text><text>b</text></para>'],
  ['CDATA', '<section><![CDATA[ ]]><para/> </section>', '<section><![CDATA[ ]]><para/></section>'],
  ['nonbreaking space', '<section>&#160;</section>', '<section/>'],
  ['Unicode thin space', '<section>&#8201;</section>', '<section/>'],
  ['attribute whitespace', '<section class="a  b"/>', '<section class="a b"/>'],
  ['attribute CR', '<section title="a&#13;b"/>', '<section title="a b"/>'],
  ['comment whitespace', '<!-- a  b -->', '<!-- a b -->'],
  ['processing instruction', '<?example value="a  b"?>', '<?example value="a b"?>'],
  ['preserve on element', '<section xml:space="preserve"> <para/></section>', '<section xml:space="preserve"><para/></section>'],
  ['inherited preserve', '<section xml:space="preserve"><para> <p>x</p></para></section>', '<section xml:space="preserve"><para><p>x</p></para></section>'],
  ['unknown xml:space', '<section xml:space="unknown"> <para/></section>', '<section xml:space="unknown"><para/></section>']) {
  my ($name, $left, $right) = @$case;
  isnt(normalized(document($left)), normalized(document($right)), "$name drift cannot qualify");
  is(normalized(document($left . '<c:ledger/>')), normalized(document($left)), "$name survives capture stripping");
}
my $reset = document('<section xml:space="preserve"><para xml:space="default"> <p>x</p> </para></section>');
is(normalized($reset), normalized(document('<section xml:space="preserve"><para xml:space="default"><p>x</p></para></section>')),
  'explicit xml:space default resumes model formatting within an element-only region');
my $alias = xml(qq{<l:document xmlns:l="$ns">\n <l:section/>\n</l:document>});
is(normalize_formatting($alias, $policy)->{record}{removed_nodes}, 2, 'namespace URI, not input prefix, selects model tags');
for my $root ('custom', 'document xmlns="urn:foreign"') {
  my $name = (split / /, $root)[0];
  my $doc = xml("<$root> <section xmlns=\"$ns\"> </section></$name>");
  is(normalize_formatting($doc, $policy)->{record}{removed_nodes}, 0, 'unknown or foreign root remains opaque');
}
XML::LibXML->new(no_blanks => 1)->load_xml(string => '<root><child/></root>');
is(normalized($pretty), normalized($plain), 'prior parser settings do not affect normalization');
isnt(normalized(document('<p> </p>')), normalized(document('<p/>')), 'prior parser settings cannot erase significant whitespace');
done_testing;
