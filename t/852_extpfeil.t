use LaTeXML::Util::Test;

subtest 'strict IR goldens' => sub {
  latexml_tests("t/extpfeil", strict => 1);
};

subtest 'unsupported composites remain undefined' => sub {
  my $core = LaTeXML::Core->new(%LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS);
  my $dom = $core->convertFile('literal:\documentclass{article}\usepackage{extpfeil}'
      . '\newextarrow{\unhandledarrow}{0599}{\diamond\relbar\rightarrow}'
      . '\begin{document}$A\unhandledarrow{v}B$\end{document}');
  ok($dom, 'rejected composition still returns the document and its residue');
  cmp_ok($core->getStatusCode, '>=', 2, 'unsupported composition is an error');
  like($core->getStatusMessage, qr/undefined macros?\[\\unhandledarrow\]/,
    'the rejected command was not silently installed');
};

done_testing();
