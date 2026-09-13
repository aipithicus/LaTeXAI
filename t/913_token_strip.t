use strict;
use warnings;
use Test::More;
use LaTeXML::Global;
use LaTeXML::Common::Object;
use Scalar::Util qw(refaddr);
use LaTeXML::Core::Tokens;
use LaTeXML::Core::Token;
{
 local $LaTeXML::Core::Tokens::CAPTURE_ACTIVE=1;
 my $original=Tokens(T_SPACE,T_BEGIN,T_BEGIN,T_OTHER('x'),T_END,T_END,T_SPACE);
 my $positions=[map {{index=>$_}} 0..6];$original->setCaptureOccurrences($positions);
 my $one=$original->stripBraces(1);my $two=$original->stripBraces(2);
 is(ToString($one),'{x}','one layer removed');
 is_deeply($one->getCaptureOccurrences,[@$positions[2..4]],'one-layer source positions follow surviving tokens');
 is(ToString($two),'x','two layers removed');
 is_deeply($two->getCaptureOccurrences,[$positions->[3]],'two-layer source position retained');
 is(ToString($original),' {{x}} ','input token sequence unchanged');
 is_deeply($original->getCaptureOccurrences,$positions,'input source positions unchanged');
 my $empty=Tokens(T_BEGIN,T_END);$empty->setCaptureOccurrences([{index=>1},{index=>2}]);
 is(ToString($empty->stripBraces),'','empty group strips to an empty sequence');
 ok(!$empty->stripBraces->hasCaptureOccurrences,'empty sequence retains no unrelated positions');
 my $plain=Tokens(T_OTHER('x'));$plain->setCaptureOccurrences([{index=>8}]);
 is(refaddr($plain->stripBraces),refaddr($plain),'untrimmed sequence retains identity');
}
{
 local $LaTeXML::Core::Tokens::CAPTURE_ACTIVE=0;
 my $plain=Tokens(T_SPACE,T_BEGIN,T_OTHER('x'),T_END,T_SPACE)->stripBraces;
 is(ToString($plain),'x','capture-off token result unchanged');
 ok(!$plain->hasCaptureOccurrences,'capture-off does not allocate source metadata');
}
done_testing;
