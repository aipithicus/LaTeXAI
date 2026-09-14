# -*- CPERL -*-
use LaTeXML::Util::Test;
latexml_tests('t/xcolor-names', strict => 1,
  requires => { '*' => ['svgnam.def', 'x11nam.def', 'dvipsnam.def'] });
