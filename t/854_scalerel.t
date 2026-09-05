use LaTeXML::Util::Test;
use XML::LibXML::XPathContext;

subtest 'strict IR goldens' => sub {
  latexml_tests("t/scalerel", strict => 1);
};

subtest 'one-sided delimiters preserve explicit parser residue' => sub {
  my $core = LaTeXML::Core->new(%LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS);
  my $dom = $core->convertFile('t/scalerel/delimiters.tex');
  ok($dom, 'delimiter document is returned');
  cmp_ok($core->getStatusCode, '<', 2, 'no engine errors are accepted');
  my $xpath = XML::LibXML::XPathContext->new($dom->getDocument);
  $xpath->registerNs(ltx => 'http://dlmf.nist.gov/LaTeXML');
  is($xpath->findvalue('count(//ltx:Math[contains(@class,"ltx_math_unparsed")])'),
    2, 'both one-sided cases are explicitly unparsed, not claimed successful');
  for my $id (qw(S0.Ex2.m1 S0.Ex4.m1)) {
    my ($math) = $xpath->findnodes('//ltx:Math[@xml:id="' . $id . '"]');
    like($math->getAttribute('class'), qr/ltx_math_unparsed/, "$id retains residue");
    is($xpath->findvalue('count(.//ltx:XMTok[text()="|"])', $math), 1,
      "$id retains its visible vertical bar");
    is($xpath->findvalue('count(.//ltx:XMTok[text()="."])', $math), 0,
      "$id does not turn the null delimiter into a period");
  }
  is($xpath->findvalue('count(//*[@meaning="parse_kludge"])'), 0,
    'no fallback kludge is accepted');
};

done_testing();
