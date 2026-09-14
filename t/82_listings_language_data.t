# -*- CPERL -*-
use strict;
use warnings;
use Test::More;
use File::Temp qw(tempdir);
use File::Path qw(make_path);
use IPC::Run3;
use LaTeXML::Core;
use LaTeXML::Package;
use LaTeXML::Core::SourceRegistry;
use LaTeXML::Package::ListingsLanguages;

my ($relative_out, $relative_err);
run3([$^X, '-I', 'lib', '-MLaTeXML::Core', '-MLaTeXML::Package::ListingsLanguages',
    '-e', 'chdir "temp" or die $!; print scalar keys %{LaTeXML::Package::ListingsLanguages::data()};'],
  undef, \$relative_out, \$relative_err);
is($?, 0, 'relative include path survives a later working-directory change') or diag($relative_err);
is($relative_out, '3', 'owned data resolves beside the loaded module');

my $tables = LaTeXML::Package::ListingsLanguages::data();
my $core = LaTeXML::Core->new(verbosity => -2, includestyles => 1, capture => 1);
$core->withState(sub {
    AssignValue(SOURCE_REGISTRY => LaTeXML::Core::SourceRegistry->new(), 'global');
    $core->initializeState('TeX.pool', 'LaTeX.pool');
    InputDefinitions('listings', type => 'sty');
    for my $file (sort keys %$tables) {
      my @actual;
      my $assign = \&LaTeXML::Core::State::assignValue;
      {
        no warnings 'redefine';
        local *LaTeXML::Core::State::assignValue = sub {
          my ($state, $key, $value) = @_;
          push(@actual, [$key, $value]) if $key =~ /^LST\@LANGUAGE\@/;
          return $assign->(@_); };
        InputDefinitions($file, noltxml => 1);
      }
      my $expected = $tables->{$file}{definitions};
      is_deeply([map { $_->[0] } @actual], [map { $_->[0] } @$expected], "$file definition order");
      for my $i (0 .. $#actual) {
        my ($name, $native) = @{$actual[$i]};
        my $generated = LaTeXML::Package::ListingsLanguages::thaw($expected->[$i][1], 'test-source', $file);
        is_deeply($generated, $native, "$name complete KeyVals and token catcodes");
        my @native_occ = map { normalized_occ($_->[1]) } @{$native->{tuples}};
        my @generated_occ = map { normalized_occ($_->[1]) } @{$generated->{tuples}};
        is_deeply(\@generated_occ, \@native_occ, "$name Mouth coordinates");
      }
    }
});
is($core->getStatusCode, 0, 'raw inventory extraction has no diagnostics');

make_path('temp/t/listings-language-data');
my $dir = tempdir('case-XXXXXX', DIR => 'temp/t/listings-language-data', CLEANUP => 1);
my $custom = "$dir/lstlang1.sty";
open(my $out, '>:raw', $custom) or die $!;
print {$out} "\\lstdefinelanguage{B5Custom}{keywords={special}}\n";
close($out);

for my $case ('stock', 'at-letter', 'other-catcode', 'custom', 'reader', 'keyval', 'catcode', 'encoding', 'contents') {
  my $engine = LaTeXML::Core->new(verbosity => -2, includestyles => 1);
  $engine->withState(sub {
      $engine->initializeState('TeX.pool', 'LaTeX.pool');
      InputDefinitions('listings', type => 'sty');
      my $file = $case eq 'custom' ? $custom : 'lstlang1.sty';
      DefMacro('\\lstalias{}{}', '') if $case eq 'reader';
      DefKeyVal('LST', 'keywords', '') if $case eq 'keyval';
      $STATE->assignCatcode('!', CC_ACTIVE) if $case eq 'catcode';
      $STATE->assignCatcode('@', CC_LETTER) if $case eq 'at-letter';
      $STATE->assignCatcode('-', CC_OTHER) if $case eq 'other-catcode';
      AssignValue(PERL_INPUT_ENCODING => 'iso-8859-1') if $case eq 'encoding';
      AssignValue($file . '_contents' => "\\lstdefinelanguage{B5Custom}{keywords={special}}") if $case eq 'contents';
      my @raw;
      my $load = \&LaTeXML::Package::loadTeXDefinitions;
      {
        no warnings 'redefine';
        local *LaTeXML::Package::loadTeXDefinitions = sub { push(@raw, $_[0]); $load->(@_); };
        LaTeXML::Package::Pool::lstInputLanguageFile($file);
      }
      is(scalar(@raw), $case =~ /^(?:stock|at-letter|other-catcode)$/ ? 0 : 1, "$case chooses the correct table reader");
      ok(LookupValue('LST@LANGUAGE@B5CUSTOM'), "$case custom definition survives")
        if $case eq 'custom' || $case eq 'contents';
      if ($case eq 'stock') {
        ok(LookupValue('LST@LANGUAGE@C$ANSI'), 'stock compiled C definition available');
        AssignValue('LST@LANGUAGE@C$ANSI' => 'sentinel', 'global');
        LaTeXML::Package::Pool::lstInputLanguageFile($file);
        is(LookupValue('LST@LANGUAGE@C$ANSI'), 'sentinel', 'already loaded table is not replayed');
      }
  });
}
my $preload = LaTeXML::Core->new(verbosity => -2, includestyles => 1);
$preload->withState(sub {
    my @raw;
    my $load = \&LaTeXML::Package::loadTeXDefinitions;
    {
      no warnings 'redefine';
      local *LaTeXML::Package::loadTeXDefinitions = sub {
        push(@raw, $_[0]) if $_[0] =~ /lstlang[123]\.sty$/;
        $load->(@_); };
      $preload->initializeState('TeX.pool', 'LaTeX.pool', 'listings');
    }
    is_deeply(\@raw, [], 'preload uses generated language tables');
    is(scalar(grep { /^LST\@LANGUAGE\@/ } keys %{$$STATE{value}}), 148, 'preload installs the complete inventory');
});
done_testing();

sub normalized_occ {
  my ($tokens) = @_;
  return undef unless $tokens->hasCaptureOccurrences;
  return [map { my $occ = $_;
      $occ ? { map { $_ => $occ->{$_} } grep { $_ ne 'source' && $_ ne 'sourceId' } keys %$occ } : undef
    } @{$tokens->getCaptureOccurrences}];
}
