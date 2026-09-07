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
