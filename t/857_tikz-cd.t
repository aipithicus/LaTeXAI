use LaTeXML::Util::Test;
use XML::LibXML::XPathContext;

subtest 'strict IR goldens' => sub {
  latexml_tests("t/tikz-cd", strict => 1);
};

subtest 'style flags do not change routing or label position' => sub {
  my $core = LaTeXML::Core->new(%LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS);
  my $dom = $core->convertFile('t/tikz-cd/styles.tex');
  cmp_ok($core->getStatusCode, '<', 2, 'style fixture has no engine errors');
  my $xp = XML::LibXML::XPathContext->new($dom->getDocument);
  $xp->registerNs(ltx => 'http://dlmf.nist.gov/LaTeXML');
  $xp->registerNs(cd => 'http://dlmf.nist.gov/LaTeXML/cd');
  is($xp->findvalue('count(//ltx:XMApp[@cd:from])'), 19, 'all claimed style branches have edges');
  my ($hook) = $xp->findnodes('//ltx:XMApp[@cd:style="hook-left"]');
  is($hook->getAttributeNS('http://dlmf.nist.gov/LaTeXML/cd', 'labelpos'), 'above',
    'hook prime changes the hook, not the label side');
  my ($left) = $xp->findnodes('//ltx:XMApp[@cd:style="leftarrow"]');
  is($left->getAttributeNS('http://dlmf.nist.gov/LaTeXML/cd', 'to'), '1-2',
    'leftarrow changes the tip, not the geometric destination');
  is($xp->findvalue('count(.//ltx:XMTok[@meaning="leftarrow"])', $left), 1,
    'leftarrow retains a left-pointing glyph');
};

subtest 'all directions survive dense-cell parser residue' => sub {
  my $core = LaTeXML::Core->new(%LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS);
  my $dom = $core->convertFile('t/tikz-cd/directions.tex');
  cmp_ok($core->getStatusCode, '<', 2, 'direction fixture has no engine errors');
  my $xp = XML::LibXML::XPathContext->new($dom->getDocument);
  $xp->registerNs(ltx => 'http://dlmf.nist.gov/LaTeXML');
  $xp->registerNs(cd => 'http://dlmf.nist.gov/LaTeXML/cd');
  is($xp->findvalue('count(//ltx:Math[contains(@class,"ltx_math_unparsed")])'), 1,
    'dense cell remains explicitly unparsed, not claimed successful');
  is($xp->findvalue('count(//ltx:XMCell)'), 25, 'all grid cells survive');
  is($xp->findvalue('count(//ltx:XMApp[@cd:from])'), 12, 'all twelve edges survive');
  my %targets = (r => '3-4', l => '3-2', u => '2-3', d => '4-3',
    ur => '2-4', ul => '2-2', dr => '4-4', dl => '4-2',
    rr => '3-5', ll => '3-1', dd => '5-3', uu => '1-3');
  for my $dir (sort keys %targets) {
    is($xp->findvalue('count(//ltx:XMApp[@cd:from="3-3" and @cd:dir="'
          . $dir . '" and @cd:to="' . $targets{$dir} . '"])'), 1,
      "$dir retains its correct numeric route");
  }
  is($xp->findvalue('count(//*[@meaning="parse_kludge"])'), 0,
    'no fallback kludge is accepted');
};

subtest 'standalone tikzcd is Math-wrapped and keeps shift/color traces' => sub {
  my $core = LaTeXML::Core->new(%LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS);
  my $dom = $core->convertFile('t/tikz-cd/standalone.tex');
  cmp_ok($core->getStatusCode, '<', 2, 'standalone fixture has no engine errors');
  my $xp = XML::LibXML::XPathContext->new($dom->getDocument);
  $xp->registerNs(ltx => 'http://dlmf.nist.gov/LaTeXML');
  $xp->registerNs(cd => 'http://dlmf.nist.gov/LaTeXML/cd');
  is($xp->findvalue('count(//ltx:XMArray)'), 2, 'two diagrams');
  is($xp->findvalue('count(//ltx:XMArray[not(ancestor::ltx:Math)])'), 0,
    'no diagram XMArray outside Math');
  is($xp->findvalue('count(//ltx:equation)'), 0,
    'standalone diagrams are not numbered equations');
  is($xp->findvalue('count(//ltx:Math)'), 2, 'each standalone diagram is one Math');
  is($xp->findvalue('count(//ltx:XMApp[@cd:from and contains(@cd:style,"shift left") and contains(@cd:style,"red")])'), 1,
    'bare shift left and red share an edge style trace');
  is($xp->findvalue('count(//ltx:XMApp[@cd:from and contains(@cd:style,"shift right") and contains(@cd:style,"blue")])'), 1,
    'bare shift right and blue share an edge style trace');
  is($xp->findvalue('count(//ltx:Math[contains(@class,"ltx_math_unparsed")])'), 0,
    'two parallel edges parse without residue');
  is($xp->findvalue('count(//*[@meaning="parse_kludge"])'), 0,
    'no fallback kludge is accepted');
};

subtest 'unsupported requests cannot masquerade as plain arrows' => sub {
  for my $body (
    '\tikzcdset{arrows=dashed}\begin{tikzcd}A\arrow[r]&B\end{tikzcd}',
    '\tikzset{every label/.style={font=\tiny}}\begin{tikzcd}A\arrow[r]&B\end{tikzcd}',
    '\begin{tikzcd}[math mode=false]A\arrow[r]&B\end{tikzcd}',
    '\begin{tikzcd}A\arrow[r,phantom]&B\end{tikzcd}',
    '\begin{tikzcd}A\arrow[r,harpoon]&B\end{tikzcd}',
    '\begin{tikzcd}A\arrow[r,Mapsto]&B\end{tikzcd}',
    '\begin{tikzcd}A\arrow[rrr]&B\end{tikzcd}',
    '\begin{tikzcd}A\arrow[r,labels={font=\tiny}]&B\end{tikzcd}',
    '\begin{tikzcd}A\arrow[r,"f","g"]&B\end{tikzcd}',
    '\begin{tikzcd}A\arrow[r,"f"{description}]&B\end{tikzcd}',
    '\begin{tikzcd}A\arrow[r,from=named-node]&B\end{tikzcd}',
    '\begin{tikzcd}A\arrow[r,to=0-1]&B\end{tikzcd}',
    '\begin{tikzcd}A\arrow{r}&B\end{tikzcd}',
    '\begin{tikzcd}A\rar&B\end{tikzcd}',
    '\begin{tikzcd}A\arrow[]&B\end{tikzcd}') {
    my $core = LaTeXML::Core->new(%LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS);
    $core->convertFile('literal:\documentclass{article}\usepackage{tikz-cd}'
        . '\begin{document}$' . $body . '$\end{document}');
    cmp_ok($core->getStatusCode, '>=', 2, 'unsupported request is an error: ' . $body);
  }
};

done_testing();
