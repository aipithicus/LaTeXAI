# -*- CPERL -*-
use strict;
use warnings;
use Test::More;
use File::Temp qw(tempdir);
use File::Path qw(make_path);
use IPC::Run3;
use JSON::PP;
use LaTeXML::Core;
use LaTeXML::Package;
use LaTeXML::Core::SourceRegistry;
use LaTeXML::Package::XColorNames;

# A process owns the binding Pool's Perl functions. Fresh processes keep
# independent engines independent, including their initialization diagnostics.
if (@ARGV && $ARGV[0] eq '--worker') {
  print JSON::PP->new->canonical->encode(worker(decode_json($ARGV[1])));
  exit 0;
}
my $tables = LaTeXML::Package::XColorNames::data();
is(scalar(@{$tables->{'svgnam.def'}{colors}}), 151, 'complete SVG source census');
is(scalar(@{$tables->{'x11nam.def'}{colors}}), 317, 'complete X11 source census');
for my $capture (0, 1) {
  my $raw = fresh({kind => 'inventory', route => 'raw', capture => $capture});
  my $generated = fresh({kind => 'inventory', route => 'generated', capture => $capture});
  for my $name (qw(svgnam x11nam)) {
    my $source = $tables->{"$name.def"}{colors};
    is_deeply([map { [$_->[0], ['rgb', @{$_}[1 .. 3]]] } @$source], $raw->{$name}{colors},
      "$name capture=$capture every generated decimal and name matches raw interpretation in order");
    is_deeply($generated->{$name}, $raw->{$name},
      "$name capture=$capture registry, public macros and loader state are identical");
  }
}
make_path('temp/t/xcolor-name-data');
my $dir = tempdir('case-XXXXXX', DIR => 'temp/t/xcolor-name-data', CLEANUP => 1);
open(my $out, '>:raw', "$dir/svgnam.def") or die $!;
print {$out} "\\definecolor{B6Custom}{rgb}{.1,.2,.3}\n"; close($out);
for my $case (qw(stock custom contents reader encoding catcode endline)) {
  my $result = fresh({kind => 'fallback', case => $case, dir => $dir});
  is($result->{rawLoads}, $case eq 'stock' ? 0 : 1, "$case selects the correct file reader");
  is_deeply($result->{custom}, ['rgb', '.1', '.2', '.3'], "$case custom color survives")
    if $case =~ /^(?:custom|contents|reader)$/;
  is_deeply($result->{repeat}, ['rgb', 1, 0, 0], 'already loaded set is not replayed') if $case eq 'stock';
}
for my $global (0, 1) {
  for my $xglobal (0, 1) {
    my $raw = fresh({kind => 'scope', route => 'raw', global => $global, xglobal => $xglobal});
    my $generated = fresh({kind => 'scope', route => 'generated', global => $global, xglobal => $xglobal});
    is_deeply($generated, $raw, "global=$global xglobal=$xglobal preserves color and macro scopes");
    is($generated->{consumed}, 0, 'xglobal flag is consumed');
  }
}
done_testing();

sub fresh {
  my ($case) = @_;
  my ($stdout, $stderr);
  run3([$^X, '-I', 'lib', __FILE__, '--worker', encode_json($case)], undef, \$stdout, \$stderr);
  is($?, 0, "$case->{kind} worker exited cleanly") or diag($stderr, $stdout);
  my $result = eval { decode_json($stdout) };
  die "Invalid worker result: $stderr $stdout $@" unless $result;
  is($result->{status}, 0, "$case->{kind} worker has no diagnostics") or diag($result->{message}, $stderr);
  ok(!$result->{unselected}, 'named tables are absent without an option');
  delete @{$result}{qw(status message unselected)};
  return $result;
}

sub worker {
  my ($case) = @_;
  my $capture = $case->{capture} || 0;
  my $core = LaTeXML::Core->new(verbosity => -2, includestyles => 1, capture => $capture);
  my %result;
  $core->withState(sub {
      AssignValue(SOURCE_REGISTRY => LaTeXML::Core::SourceRegistry->new(), 'global') if $capture;
      $core->initializeState('TeX.pool', 'LaTeX.pool');
      InputDefinitions('xcolor', type => 'sty');
      $result{unselected} = LookupValue('color_AliceBlue') || LookupValue('color_AntiqueWhite1') ? 1 : 0;
      if ($case->{kind} eq 'inventory') {
        for my $name (qw(svgnam x11nam)) {
          my @colors;
          my $assign = \&LaTeXML::Core::State::assignValue;
          DefMacroI('\\colornameprefix', undef, 'before');
          {
            no warnings 'redefine';
            local *LaTeXML::Core::State::assignValue = sub {
              my ($state, $key, $value) = @_;
              push(@colors, [$1, [@$value]]) if $key =~ /^color_(.*)$/;
              return $assign->(@_); };
            load_names($case->{route}, $name);
          }
          $result{$name} = { colors => \@colors,
            macros => [map { ToString(Expand(T_CS('\\\\color@' . $_->[0]))) } @colors],
            prefix => ToString(Expand(T_CS('\\colornameprefix'))),
            version => ToString(Expand(T_CS('\\ver@' . $name . '.def'))),
            loaded => LookupValue($name . '.def_loaded'), xglobal => LookupValue('xglobal@') };
        }
      }
      elsif ($case->{kind} eq 'fallback') {
        my $kind = $case->{case};
        my $name = $kind eq 'custom' ? "$case->{dir}/svgnam" : 'svgnam';
        AssignValue(FindFile("$name.def") . '_contents' => '\\definecolor{B6Custom}{rgb}{.1,.2,.3}') if $kind eq 'contents';
        DefMacro('\\preparecolorset{}{}{}{}', '\\definecolor{B6Custom}{rgb}{.1,.2,.3}') if $kind eq 'reader';
        AssignValue(PERL_INPUT_ENCODING => 'iso-8859-1') if $kind eq 'encoding';
        RawTeX('\\endlinechar=-1 ') if $kind eq 'endline';
        $STATE->assignCatcode(';', CC_ACTIVE) if $kind eq 'catcode';
        my @raw;
        my $load = \&LaTeXML::Package::loadTeXDefinitions;
        {
          no warnings 'redefine';
          local *LaTeXML::Package::loadTeXDefinitions = sub {
            push(@raw, $_[0]);
            # An active separator changes the grammar. Observe dispatch here;
            # the custom-content cases above verify actual raw interpretation.
            return if $kind eq 'catcode';
            $load->(@_); };
          load_names('generated', $name);
        }
        $result{rawLoads} = scalar(@raw);
        $result{custom} = [@{LookupValue('color_B6Custom') || []}];
        if ($kind eq 'stock') {
          DefColor('AliceBlue', Color('rgb', 1, 0, 0));
          load_names('generated', $name);
          $result{repeat} = [@{LookupValue('color_AliceBlue')}];
        }
      }
      else {
        RawTeX('\\globalcolorstrue') if $case->{global};
        $STATE->pushFrame;
        AssignValue('xglobal@' => $case->{xglobal});
        load_names($case->{route}, 'svgnam');
        $result{consumed} = LookupValue('xglobal@');
        $STATE->popFrame;
        $result{color} = LookupValue('color_AliceBlue') ? [@{LookupValue('color_AliceBlue')}] : undef;
        $result{macro} = $STATE->lookupMeaning(T_CS('\\\\color@AliceBlue')) ? 1 : 0;
      }
  });
  return { %result, status => $core->getStatusCode, message => $core->getStatusMessage };
}

sub load_names {
  my ($route, $name) = @_;
  return $route eq 'raw' ? InputDefinitions($name, type => 'def', noltxml => 1)
    : LaTeXML::Package::Pool::xcInputNamedColors($name);
}
