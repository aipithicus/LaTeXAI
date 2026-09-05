use LaTeXML::Util::Test;

subtest 'strict IR goldens' => sub {
  latexml_tests("t/nicematrix", strict => 1);
};

subtest 'unsupported notation is reported, not silently dropped' => sub {
  for my $case (
    ['light syntax', '\begin{NiceMatrix}[light-syntax] a & b \end{NiceMatrix}'],
    ['dot options', '\begin{NiceMatrix}[nullify-dots,renew-dots] a \end{NiceMatrix}'],
    ['matrix replacement', '\NiceMatrixOptions{renew-matrix}\begin{NiceMatrix}a\end{NiceMatrix}'],
    ['unknown option', '\begin{NiceMatrix}[not-a-key]a\end{NiceMatrix}'],
    ['block span', '\begin{NiceMatrix}\Block{2-2}{a}&b\\c&d\end{NiceMatrix}'],
    ['block styling', '\begin{NiceMatrix}\Block[draw]{1-1}{a}\end{NiceMatrix}'],
    ['block format', '\begin{NiceMatrix}\Block{1-1}<\bfseries>{a}\end{NiceMatrix}'],
    ['misplaced transparent option', '\begin{NiceMatrix}[transparent]a\end{NiceMatrix}'],
    ['post-matrix code', '\begin{NiceMatrix}a\CodeAfter\text{annotation}\end{NiceMatrix}'],
    ['dotted notation', '\begin{NiceMatrix}a&\Cdots&b\end{NiceMatrix}']) {
    my ($name, $body) = @$case;
    my $core = LaTeXML::Core->new(%LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS);
    $core->convertFile('literal:\documentclass{article}\usepackage{nicematrix}'
        . '\begin{document}$' . $body . '$\end{document}');
    cmp_ok($core->getStatusCode, '>=', 2, "$name cannot produce a clean golden");
  }
  for my $option (qw(renew-dots renew-matrix messages-for-Overleaf footnote footnotehyper)) {
    my $core = LaTeXML::Core->new(%LaTeXML::Util::Test::CORE_OPTIONS_FOR_TESTS);
    $core->convertFile('literal:\documentclass{article}\usepackage[' . $option
        . ']{nicematrix}\begin{document}$a$\end{document}');
    cmp_ok($core->getStatusCode, '>=', 2, "package option $option is explicitly unsupported");
  }
};

done_testing();
