use strict;
use warnings;
use Test::More;
use Scalar::Util qw(refaddr);
use LaTeXML::Core;
use LaTeXML::Core::Gullet;
use LaTeXML::Core::Token;
use LaTeXML::Core::Tokens;

my $core = LaTeXML::Core->new(capture => 1, verbosity => -3);
$core->withState(sub {
    local $LaTeXML::ALIGN_STATE = 100;
    my $gullet = LaTeXML::Core::Gullet->new;
    my $origin = { sourceId => 'source', byteStart => 7, byteEnd => 8 };
    my $template = { generated => 1, origin => $origin, authorCallsite => $origin,
      frameId => 3, token => T_OTHER('old') };
    my @tokens = (T_BEGIN, T_LETTER('a'), T_END, T_LETTER('b'));
    $gullet->unreadWithOccurrence($template,
      TokensI($tokens[0], TokensI($tokens[1], undef, $tokens[2])), $tokens[3]);
    is_deeply($gullet->{pushback}, \@tokens, 'nested unread keeps token order and omits absent tokens');
    is($LaTeXML::ALIGN_STATE, 100, 'balanced unread preserves alignment');
    my @occ = @{ $gullet->{pushback_occurrences} };
    is(scalar(@occ), 4, 'one occurrence slot per flattened token');
    for my $i (0 .. $#tokens) {
      isnt(refaddr($occ[$i]), refaddr($template), "token $i owns a fresh occurrence hash");
      is(refaddr($occ[$i]{token}), refaddr($tokens[$i]), "token $i has its own token identity");
      is(refaddr($occ[$i]{origin}), refaddr($origin), "token $i retains shallow origin identity");
      is(refaddr($occ[$i]{authorCallsite}), refaddr($origin), "token $i retains author callsite identity");
    }
    $template->{frameId} = 99;
    $occ[0]{frameId} = 42;
    is_deeply([map { $_->{frameId} } @occ], [42, 3, 3, 3],
      'caller mutation and one replayed token cannot alter sibling occurrences');
    is($template->{token}->toString, 'old', 'unread never changes the caller token field');

    $gullet = LaTeXML::Core::Gullet->new;
    $gullet->unreadWithOccurrence(undef, TokensI(T_BEGIN, T_LETTER('a')));
    is_deeply($gullet->{pushback_occurrences}, [undef, undef], 'undefined template preserves all slots');
    is($LaTeXML::ALIGN_STATE, 99, 'unread retracts an unmatched opening brace');
    $gullet->unreadWithOccurrence($template, undef, TokensI());
    is(scalar(@{ $gullet->{pushback} }), 2, 'empty unread adds no tokens or occurrences');

    # Stored source/expansion/callsite occurrences survive substitution. A
    # generated or absent slot receives the invocation template, independently.
    $gullet = LaTeXML::Core::Gullet->new;
    my @body = map { T_LETTER($_) } qw(a b c d e f);
    my $stored = { sourceId => 'argument', byteStart => 20, byteEnd => 21 };
    my $inherited = { generated => 1, origin => $stored };
    my $author = { generated => 1, authorCallsite => $stored };
    my $input = TokensI(@body)->setCaptureOccurrences(
      [$stored, undef, { generated => 1 }, $inherited, $author, $stored]);
    my $invocation = { sourceId => 'invocation', source => 'paper.tex',
      byteStart => 10, byteEnd => 15, fromLine => 1, fromCol => 10,
      toLine => 1, toCol => 15, token => T_CS('macro') };
    $gullet->unreadExpansion($input, undef, $invocation);
    @occ = @{ $gullet->{pushback_occurrences} };
    is_deeply([map { my (undef, $resolved) = $gullet->resolveOccurrence($_);
          $resolved->{sourceId} } @occ],
      [qw(argument invocation invocation argument argument argument)],
      'expansion preserves stored provenance and fills only generated slots');
    for my $i (0 .. $#body) {
      is(refaddr($occ[$i]{token}), refaddr($body[$i]), "expansion token $i owns its token identity");
    }
    isnt(refaddr($occ[0]), refaddr($stored), 'substitution does not transfer ownership of stored hash');
    isnt(refaddr($occ[0]), refaddr($occ[5]), 'repeated argument occurrences have separate hashes');
    isnt(refaddr($occ[1]), refaddr($occ[2]), 'generated expansion siblings have separate hashes');
    is(refaddr($occ[3]{origin}), refaddr($stored), 'stored expansion origin is retained');
    is(refaddr($occ[4]{authorCallsite}), refaddr($stored), 'stored author callsite is retained');
    $occ[1]{generated} = 0;
    is($occ[2]{generated}, 1, 'mutating one generated sibling cannot change another');
    $occ[0]{byteStart} = 200;
    is($stored->{byteStart}, 20, 'mutating replay cannot change stored argument provenance');
    is($occ[5]{byteStart}, 20, 'mutating replay cannot change repeated argument provenance');
    ok(!exists $stored->{token}, 'stored source hash is not assigned an expansion token');
    return;
  });

my $ordinary = LaTeXML::Core->new(capture => 0, verbosity => -3);
$ordinary->withState(sub {
    local $LaTeXML::ALIGN_STATE = 100;
    no warnings 'redefine';
    local *LaTeXML::Core::Gullet::_cloneOccurrence = sub { die 'capture OFF cloned an occurrence'; };
    local *LaTeXML::Core::Gullet::_flattenUnreadWithOccurrences = sub { die 'capture OFF scanned occurrences'; };
    my $gullet = LaTeXML::Core::Gullet->new;
    $gullet->unread(TokensI(T_BEGIN, T_LETTER('a')), T_END);
    $gullet->unreadExpansion(TokensI(T_LETTER('b')), undef, undef);
    is(join('', map { $_->toString } @{ $gullet->{pushback} }), 'b{a}',
      'capture OFF unread and expansion keep token order without occurrence work');
    is_deeply($gullet->{pushback_occurrences}, [], 'capture OFF does not create occurrence slots');
    is($LaTeXML::ALIGN_STATE, 100, 'capture OFF preserves alignment');
    return;
  });
done_testing();
