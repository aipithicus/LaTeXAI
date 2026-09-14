# -*- CPERL -*-
use LaTeXML::Util::Test;
latexml_tests('t/listings-languages', strict => 1,
  requires => { '*' => ['listings.cfg', 'lstlang1.sty', 'lstlang2.sty', 'lstlang3.sty'] });
