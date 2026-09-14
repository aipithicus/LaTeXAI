# -*- CPERL -*-
use LaTeXML::Util::Test;
latexml_tests('t/babel-dispatch', strict => 1,
  requires => { '*' => ['babel.sty', 'babel.def', 'english.ldf'] });
