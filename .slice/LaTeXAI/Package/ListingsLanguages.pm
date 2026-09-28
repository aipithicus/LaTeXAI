# Generated-table codec owned by listings.sty.ltxml, not an independent binding.
package LaTeXML::Package::ListingsLanguages;
use strict;
use warnings;
use LaTeXML::Package;
use LaTeXML::Core::KeyVals;
use File::Basename qw(dirname basename);
use File::Spec;
my $DATA;
my $DATA_PATH = File::Spec->rel2abs(dirname(__FILE__) . '/listings.languages.pl');

sub data {
  return $DATA if $DATA;
  my $path = $DATA_PATH;
  my $tables = do $path;
  die "Cannot read generated listings data $path: " . ($@ || $! || 'invalid data')
    unless ref($tables) eq 'HASH';
  return $DATA = $tables;
}

# Only the table's actual token stream is serialized: no retokenization or TeX
# string round trip. The compact occurrence rows refer to this table's Mouth.
sub freeze {
  my ($keyvals, $file) = @_;
  my %result = map { $_ => $$keyvals{$_} }
    qw(prefix keysets skip setAll setInternals skipMissing hookMissing);
  die 'Unsupported listings KeyVals hooks' if ref($result{skipMissing}) || ref($result{hookMissing});
  my @tuples;
  foreach my $tuple (@{$$keyvals{tuples}}) {
    my ($key, $value, @rest) = @$tuple;
    die "Non-token listings value $key" unless ref($value) eq 'LaTeXML::Core::Tokens';
    my @runs;
    foreach my $token ($value->unlist) {
      my ($text, $cc) = @$token;
      die "Unsupported listings token" if @$token != 2 || ($cc != CC_CS && length($text) != 1);
      if (@runs && $cc != CC_CS && $runs[-1][0] == $cc) { $runs[-1][1] .= $text; }
      else { push(@runs, [$cc, $text]); }
    }
    my $coordinates;
    if ($value->hasCaptureOccurrences) {
      my @rows;
      foreach my $occ (@{$value->getCaptureOccurrences}) {
        if (!$occ) { push(@rows, undef); next; }
        die "Non-source listings occurrence" if $occ->{generated}
          || basename($occ->{source} || '') ne $file
          || grep { !/^(?:token|source|sourceId|fromLine|fromCol|toLine|toCol|byteStart|byteEnd|generated)$/ } keys %$occ;
        push(@rows, [map { defined($occ->{$_}) ? $occ->{$_} : die "Missing $_" }
            qw(fromLine fromCol toLine toCol byteStart byteEnd)]);
      }
      # Arithmetic runs compact consecutive Mouth coordinates without deriving
      # any positions from token text. A null run keeps synthetic gaps intact.
      my @runs;
      for (my $i = 0; $i < @rows;) {
        my $start = $rows[$i];
        my $count = 1;
        my @step;
        if (!$start) {
          $count++ while $i + $count < @rows && !$rows[$i + $count];
          push(@runs, "$count");
        }
        else {
          if ($i + 1 < @rows && $rows[$i + 1]) {
            @step = map { $rows[$i + 1][$_] - $start->[$_] } 0 .. 5;
            $count = 2;
            while ($i + $count < @rows && $rows[$i + $count]
              && !grep { $rows[$i + $count][$_] != $start->[$_] + $count * $step[$_] } 0 .. 5) { $count++; }
          }
          push(@runs, join(',', $count, @$start, @step));
        }
        $i += $count;
      }
      $coordinates = join(';', @runs);
    }
    push(@tuples, [$key, [\@runs, $coordinates], @rest]);
  }
  $result{tuples} = \@tuples;
  return \%result;
}

sub thaw {
  my ($record, $source_id, $source) = @_;
  my @tuples;
  foreach my $tuple (@{$$record{tuples}}) {
    my ($key, $encoded, @rest) = @$tuple;
    my @tokens = map { my ($cc, $text) = @$_;
      $cc == CC_CS ? Token($text, $cc) : map { Token($_, $cc) } split(//, $text)
    } @{$encoded->[0]};
    my $value = Tokens(@tokens);
    if ($source_id && defined($encoded->[1])) {
      my @rows;
      for my $run (split(/;/, $encoded->[1])) {
        my ($count, @numbers) = split(/,/, $run);
        if (!@numbers) { push(@rows, (undef) x $count); next; }
        die 'Invalid listings coordinate run' unless @numbers == 6 || @numbers == 12;
        for my $i (0 .. $count - 1) {
          push(@rows, [map { $numbers[$_] + $i * ($numbers[$_ + 6] || 0) } 0 .. 5]); }
      }
      die 'Invalid listings occurrence count' unless @rows == @tokens;
      my @occurrences;
      for my $i (0 .. $#tokens) {
        if (!$rows[$i]) { push(@occurrences, undef); next; }
        my %occ;
        @occ{qw(fromLine fromCol toLine toCol byteStart byteEnd)} = @{$rows[$i]};
        push(@occurrences, { %occ, token => $tokens[$i], sourceId => $source_id,
            source => $source, generated => 0 });
      }
      $value->setCaptureOccurrences(\@occurrences);
    }
    push(@tuples, [$key, $value, @rest]);
  }
  return LaTeXML::Core::KeyVals->new($$record{prefix}, $$record{keysets},
    (map { $_ => $$record{$_} } qw(skip setAll setInternals skipMissing hookMissing)), tuples => \@tuples);
}
1;
