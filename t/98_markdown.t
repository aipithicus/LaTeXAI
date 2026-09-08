use strict;
use warnings;
use utf8;
use Test::More;
use XML::LibXML;
use LaTeXAI::Post::Markdown;
use LaTeXAI::Post;
use File::Temp qw(tempfile);

sub dom { XML::LibXML->load_xml(string => '<document xmlns="http://dlmf.nist.gov/LaTeXML">' . $_[0] . '</document>') }
sub project { LaTeXAI::Post::Markdown->new(toc => 0)->project(dom($_[0]), strategy => $_[1] || 'deferred') }
my $source = <<'XML';
<title>A manuscript</title>
<creator><personname>Some Author</personname><contact>Some University</contact></creator>
<abstract><p>An abstract.</p></abstract>
<section xml:id="S1" labels="LABEL:intro"><tags><tag role="refnum">1</tag></tags><title><tag close=" ">1</tag>Introduction</title>
<para><p>See <ref labelref="LABEL:end"/> and <cite>[<bibref bibrefs="B,A"/>]</cite>.</p>
<p>a<emph> b </emph>c and <Math mode="inline" tex="x_1"><XMath><SECRET>never print this</SECRET></XMath></Math>.</p></para>
<equation xml:id="E1"><tags><tag>(1)</tag><tag role="refnum">1</tag></tags><MathFork>
<Math tex="a=b"><XMath/></Math><MathBranch><Math tex="duplicate"><XMath/></Math></MathBranch>
</MathFork></equation>
<figure><graphics graphic="one.eps"/><toccaption>Duplicated caption</toccaption><caption>Full caption.</caption></figure>
<enumerate><item><para><p>First.</p></para></item><item><p>Second.</p></item></enumerate>
</section>
<section xml:id="S2" labels="LABEL:end"><tags><tag role="refnum">2</tag></tags><title><tag close=" ">2</tag>End</title><p>Fin.</p></section>
<bibliography><title>References</title><biblist>
<bibitem key="A" xml:id="bib.A"><bibblock>Alpha. A title.</bibblock></bibitem>
<bibitem key="B" xml:id="bib.B"><bibblock>Beta. Another title.</bibblock></bibitem>
</biblist></bibliography>
XML
my $input = dom($source);
my $original = $input->toString;
my $one = LaTeXAI::Post::Markdown->new->project($input);
my $two = LaTeXAI::Post::Markdown->new->project($input, strategy => 'indexed');
is($one->{markdown}, $two->{markdown}, 'traversal strategies produce identical Markdown');
is($input->toString, $original, 'projection leaves IR unchanged');
like($one->{markdown}, qr/See \[2\]\(#2-end\) and \\\[2, 1\\\]/, 'forward section and bibliography references resolve');
like($one->{markdown}, qr/a \*b\* c and \$x_1\$/, 'mixed-content spaces and math carrier survive');
like($one->{markdown}, qr/\$\$\na=b\n\$\$/, 'equation context supplies display mode');
unlike($one->{markdown}, qr/SECRET|never print|duplicate|Duplicated caption/, 'math interior, alternative branch and TOC caption excluded');
like($one->{markdown}, qr/\[Figure asset\]\(<one.eps>\)/, 'unsupported image format remains an asset link');
like($one->{markdown}, qr/1\. First\.\n2\. Second\./, 'enumeration maintains item order');
like($one->{markdown}, qr/\[1\] Alpha\. A title\.\n\n\[2\] Beta\./, 'bibliography numbered in document order');
is(scalar @{$one->{report}{math}}, 2, 'selected math occurrences counted once');
is($one->{report}{counters}{index_visits}, 0, 'deferred walker has no metadata prepass');
ok($two->{report}{counters}{index_visits} > 0, 'indexed walker measures its prepass');
is($two->{report}{counters}{deferred_references}, 0, 'indexed walker resolves references during emission');

my $table = project(<<'XML');
<title>Tables</title><tabular><tbody>
<tr><td rowspan="2">row</td><td colspan="2">columns</td></tr>
<tr><td><Math tex="a|b"><XMath/></Math></td><td>end</td></tr>
</tbody></tabular>
XML
like($table->{markdown}, qr/\| row \| columns \|  \|\n\| --- \| --- \| --- \|\n\|  \| \$a\\\|b\$ \| end \|/, 'table spans reserve correct cells and protect math pipes');
is(scalar(grep { $_->{kind} eq 'flattened-table-span' } @{$table->{report}{issues}}), 2, 'flattened spans reported');
my $unknown = project('<title>Residue</title><p><ref labelref="missing"/></p><novel><p>Keep this.</p></novel><picture xml:id="pic"/>');
like($unknown->{markdown}, qr/reference: missing/, 'dangling reference visible');
like($unknown->{markdown}, qr/unhandled novel.*Keep this/s, 'unknown wrapper retains prose and visible residue');
like($unknown->{markdown}, qr/picture pic/, 'opaque picture has a visible marker');
is(scalar @{$unknown->{report}{issues}}, 3, 'diagnostics account for unsupported content');

my $math = "x  +\n\n y";
my $opaque = project('<title>Math</title><p><Math mode="display" tex="x  +&#10;&#10; y"><XMath/></Math></p>');
like($opaque->{markdown}, qr/\Q$math\E/, 'math internal whitespace is not prose-normalized');
my $ay = project('<title>Bib</title><bibliography><bibitem key="x"><tags><tag role="refnum" class="ltx_bib_author-year">Author (2000)</tag></tags><bibblock>Title.</bibblock></bibitem></bibliography>');
like($ay->{markdown}, qr/\[1\] Author \(2000\)\. Title\./, 'author-year tag restored when bibblocks omit it');
my $notes = project('<title>Notes</title><p>Word<note>First <emph>note</emph>.</note>.</p>');
like($notes->{markdown}, qr/Word\[\^1\]\./, 'note marker stays inline');
like($notes->{markdown}, qr/\[\^1\]: First \*note\*\./, 'note text emitted once at end');
my $order = dom('<title>Contents</title><bibliography><title>References</title><bibitem key="z"><bibblock>Z.</bibblock></bibitem></bibliography>'
  . '<section xml:id="s"><title>Contents</title><subsection><title>Nested</title><p>body</p></subsection></section>'
  . '<section><title>References</title><p>Appendix material.</p></section><p>See <ref idref="s"/>.</p>');
my $ordered = LaTeXAI::Post::Markdown->new->project($order);
is($ordered->{markdown}, LaTeXAI::Post::Markdown->new->project($order, strategy => 'indexed')->{markdown}, 'both strategies allocate anchors in final manuscript order');
like($ordered->{markdown}, qr/- \[Contents\]\(#contents-2\)\n  - \[Nested\]/, 'TOC preserves nesting and reserves title plus Contents anchors');
like($ordered->{markdown}, qr/\[References\]\(#references\).*\[References\]\(#references-1\)/s, 'bibliography anchor follows relocated bibliography order');
like($ordered->{markdown}, qr/Appendix material.*## References\n\n\[1\] Z\./s, 'bibliography is emitted after every body section');

my $nested = project('<title>Lists</title><enumerate><item><p>Outer.</p><itemize><item><p>Inner.</p></item></itemize><p>Still outer.</p></item><item><p>Next.</p></item></enumerate>');
like($nested->{markdown}, qr/1\. Outer\.\n   \n   - Inner\.\n   \n   Still outer\.\n2\. Next\./, 'nested list and following paragraph stay inside their parent item');
my $fork = project('<title>Fork</title><p><MathFork><text>for <Math tex="u=v"/>,</text><MathBranch><Math tex="discard"/></MathBranch></MathFork></p>');
like($fork->{markdown}, qr/for \$u=v\$,/, 'text primary in MathFork retains its inline math');
unlike($fork->{markdown}, qr/discard|unavailable/, 'text primary suppresses alternate branch without residue');

my $citation = project('<title>Cite</title><p><bibref bibrefs="a" show="Authors Phrase1YearPhrase2"><bibrefphrase>(</bibrefphrase><bibrefphrase>)</bibrefphrase></bibref></p>'
  . '<bibliography><bibitem key="a"><tags><tag role="authors">Author</tag><tag role="year">2000</tag></tags><bibblock>A.</bibblock></bibitem></bibliography>');
like($citation->{markdown}, qr/Author \(2000\)/, 'citation show pattern preserves the space before parentheses');
my $bib = project('<title>Bib</title><bibliography><bibitem key="a"><bibblock>A. (<bib-date>2000</bib-date>) <bib-title>Title.</bib-title> <bib-publisher>Press.</bib-publisher></bibblock></bibitem></bibliography>');
like($bib->{markdown}, qr/\[1\] A\. \(2000\) Title\. Press\./, 'prepared bibliography fields remain ordinary manuscript prose');
is(scalar @{$bib->{report}{issues}}, 0, 'known bibliography field wrappers need no residue');
my $algorithm = project('<title>Algorithm</title><listing><listingline><text font="bold">repeat</text> <Math tex="x&#10;+y"/></listingline><listingline>done</listingline></listing>');
like($algorithm->{markdown}, qr/> \*\*repeat\*\* \$x\n> \+y\$\n> done/, 'algorithm continuation lines stay in their quote block');

my $zero_source = '<title>At <Math xml:id="title-zero" tex="0"/></title>'
  . '<section><title>Case <MathFork><Math xml:id="heading-zero" tex="0"/><MathBranch><Math tex="discard"/></MathBranch></MathFork></title>'
  . '<p>Away from <Math xml:id="body-zero" tex="0"/> and <Math tex="\pi"/>.</p>'
  . '<p><Math xml:id="absent"/><Math xml:id="empty" tex=""/></p></section>';
for my $strategy (qw(deferred indexed)) {
  my $zero = LaTeXAI::Post::Markdown->new->project(dom($zero_source), strategy => $strategy);
  like($zero->{markdown}, qr/^# At \$0\$/m, "$strategy: document title preserves zero");
  like($zero->{markdown}, qr/- \[Case \$0\$\]\(#case-0\).*## Case \$0\$/s, "$strategy: heading and contents preserve primary zero math");
  like($zero->{markdown}, qr/Away from \$0\$ and \$\\pi\$\./, "$strategy: body preserves zero beside nonzero notation");
  is_deeply([sort map { $_->{id} } grep { $_->{kind} eq 'missing-math-tex' } @{$zero->{report}{issues}}],
    [qw(absent empty)], "$strategy: only absent and empty carriers are missing");
}

my $heading_source = <<'XML';
<title>Results of Theorem <ref idref="thm"/></title>
<section xml:id="proof"><title>Proof of Theorem <ref idref="thm"/></title>
<p>See <ref idref="proof" show="title"/> and <ref idref="same"/>.</p>
<theorem xml:id="thm"><tags><tag role="refnum">1</tag></tags><title>Theorem 1 (<ref idref="later" show="title"/>)</title><p>Statement.</p></theorem>
<equation xml:id="eq"><tags><tag>(<ref idref="thm"/>)</tag></tags><Math tex="x=0"/></equation>
</section>
<section xml:id="same"><title>Proof of Theorem 1</title></section>
<section xml:id="later"><title>Bound from <ref href="https://example.org">External</ref> [<bibref bibrefs="a"/>]</title></section>
<section><title>By <bibref bibrefs="a" show="Authors Phrase1YearPhrase2"><bibrefphrase>(</bibrefphrase><bibrefphrase>)</bibrefphrase></bibref></title></section>
<bibliography><title>References</title><bibitem key="a"><tags><tag role="authors">Author</tag><tag role="year">2000</tag></tags><bibblock>A.</bibblock></bibitem></bibliography>
XML
my $heading_dom = dom($heading_source);
my $heading_xml = $heading_dom->toString;
my $heading_deferred = LaTeXAI::Post::Markdown->new->project($heading_dom);
my $heading_indexed = LaTeXAI::Post::Markdown->new->project($heading_dom, strategy => 'indexed');
is($heading_deferred->{markdown}, $heading_indexed->{markdown}, 'both strategies resolve forward and chained label references identically');
is($heading_dom->toString, $heading_xml, 'label resolution does not mutate the IR');
like($heading_deferred->{markdown}, qr/^# Results of Theorem 1$/m, 'document title resolves a forward theorem reference');
like($heading_deferred->{markdown}, qr/- \[Proof of Theorem 1\]\(#proof-of-theorem-1\)/, 'TOC links the resolved plain heading text');
like($heading_deferred->{markdown}, qr/See \[Proof of Theorem 1\]\(#proof-of-theorem-1\) and \[Proof of Theorem 1\]\(#proof-of-theorem-1-1\)/,
  'body references use anchors allocated after heading resolution, including collisions');
like($heading_deferred->{markdown}, qr/\*\*Theorem 1 \(Bound from External \\\[1\\\]\)\*\*/, 'theorem label resolves a forward title containing citation and hyperlink text');
like($heading_deferred->{markdown}, qr/\$\$\nx=0\n\$\$\n\n\(1\)/, 'equation display tag uses resolved reference text');
like($heading_deferred->{markdown}, qr/^## By Author \(2000\)$/m, 'heading citation preserves author-year phrasing');
is(scalar @{$heading_deferred->{report}{issues}}, 0, 'resolved label references have no residue diagnostics');
is($heading_deferred->{report}{counters}{index_visits}, 0, 'forward label resolution requires no DOM metadata prepass');

my $bad_labels = '<title>References</title><section xml:id="a"><title>A <ref idref="b" show="title"/></title></section>'
  . '<section xml:id="b"><title>B <ref idref="a" show="title"/></title></section>'
  . '<section><title>Missing <ref idref="absent"/> and [<bibref bibrefs="unknown"/>]</title></section>';
my $bad_deferred = LaTeXAI::Post::Markdown->new->project(dom($bad_labels));
my $bad_indexed = LaTeXAI::Post::Markdown->new->project(dom($bad_labels), strategy => 'indexed');
is($bad_deferred->{markdown}, $bad_indexed->{markdown}, 'cyclic and missing labels degrade identically in both strategies');
like($bad_deferred->{markdown}, qr/cyclic label/, 'cyclic title reference remains explicit instead of recursing indefinitely');
is_deeply([sort map { $_->{kind} } @{$bad_deferred->{report}{issues}}],
  [qw(cyclic-label-reference unresolved-citation unresolved-reference)], 'label failures reported once despite reuse in heading and contents');
my $unlabeled = project('<title>Cases</title><section><title>Case <ref idref="item"/></title></section>'
  . '<description><item xml:id="item"><tags><tag>Case D (condition)</tag></tags><p>Body.</p></item></description>');
like($unlabeled->{markdown}, qr/## Case \\\[reference: item\\\]/, 'a target with only a display tag keeps an explicit unresolved label');
is_deeply($unlabeled->{report}{issues}, [{kind => 'unlabeled-reference', key => 'item'}],
  'missing reference text is distinguished from a missing target');

# The repository parser returns undef for absent attributes in parsed files.
my $captured_labels = <<'XML';
<section><title>Case <ref labelref="LABEL:custom"/></title></section>
<description><item xml:id="case" labels="LABEL:custom LABEL:zero LABEL:empty LABEL:syntax"
 xmlns:capture="http://dlmf.nist.gov/LaTeXML/capture"
 capture:labelValues='{"LABEL:custom":"D","LABEL:zero":"0","LABEL:empty":"","LABEL:syntax":"a_b"}'>
<tags><tag>Case D (condition)</tag><tag role="refnum">wrong fallback</tag></tags><p>Body.</p></item></description>
<p><ref labelref="LABEL:zero"/>; <ref labelref="LABEL:syntax"/>; <ref labelref="LABEL:empty"/>.</p>
XML
for my $strategy (qw(deferred indexed)) {
  my $values = project($captured_labels, $strategy);
  like($values->{markdown}, qr/## Case D/, "$strategy uses the label-time value in headings");
  like($values->{markdown}, qr/0; a\\_b;/, "$strategy preserves zero and escapes label text");
  is_deeply($values->{report}{issues}, [{kind => 'unlabeled-reference', key => 'LABEL:empty'}],
    "$strategy distinguishes empty captured values from absent metadata"); }
my $invalid_values = project('<item xml:id="bad" xmlns:capture="http://dlmf.nist.gov/LaTeXML/capture" capture:labelValues="[]"><p>Body.</p></item>');
ok(grep($_->{kind} eq 'invalid-label-values', @{$invalid_values->{report}{issues}}),
  'malformed label metadata is reported');

# The repository parser returns undef for absent attributes in parsed files.
my ($xmlfh, $xmlpath) = tempfile(SUFFIX => '.xml', UNLINK => 1);
binmode $xmlfh, ':raw';
print {$xmlfh} '<document xmlns="http://dlmf.nist.gov/LaTeXML"><title>Quiet</title><section xml:id="s"><title><tag>1</tag> Name</title><p>Body.</p></section></document>';
close $xmlfh;
my @warnings;
{ local $SIG{__WARN__} = sub { push @warnings, @_ };
  LaTeXAI::Post::Markdown->new->project(LaTeXAI::Post->load_file($xmlpath)); }
is_deeply(\@warnings, [], 'file parser attributes produce no Perl warnings');

eval { project('<title>Bad</title>', 'bogus') }; like($@, qr/Unknown traversal/, 'invalid strategy refuses');
done_testing;
