# -*- CPERL -*-
# lib-symb tables against provenance. Does not need vendored tex/ trees.
use strict;
use warnings;
use FindBin;
use File::Spec;
use JSON::PP;
use Test::More;
use Encode qw(decode_utf8);

my $root = File::Spec->catdir($FindBin::Bin, '..');
my $symb = File::Spec->catdir($root, 'lib-symb');

ok(-f File::Spec->catfile($symb, 'README.md'), 'lib-symb README exists');

my $header = join("\t",
  qw(command kind mode codepoint name meaning role font katex source note));

sub load_tsv {
  my ($path) = @_;
  open my $fh, '<:raw', $path or die "read $path: $!";
  my $raw = do { local $/; <$fh> };
  close $fh;
  $raw =~ s/\r\n/\n/g;
  $raw =~ s/\n\z//;
  my @lines = split /\n/, decode_utf8($raw), -1;
  my $h = shift @lines;
  return ($h, \@lines);
}

sub collect_tables {
  my @got;
  my $kernel = File::Spec->catfile($symb, '_kernel', 'symbols.tsv');
  push @got, ['_kernel', $kernel] if -f $kernel;
  my $late = File::Spec->catdir($symb, '_latexml');
  if (-d $late) {
    opendir my $dh, $late or die "read $late: $!";
    for my $n (sort grep { !/^\./ } readdir $dh) {
      my $p = File::Spec->catfile($late, $n, 'symbols.tsv');
      push @got, [$n, $p] if -f $p;
    }
    closedir $dh;
  }
  opendir my $dh, $symb or die "read $symb: $!";
  for my $n (sort grep { !/^\./ && $_ ne '_kernel' && $_ ne '_latexml' } readdir $dh) {
    my $p = File::Spec->catfile($symb, $n, 'symbols.tsv');
    push @got, [$n, $p] if -f $p;
  }
  closedir $dh;
  return @got;
}

my @tables = collect_tables();
ok(scalar @tables, 'at least one symbols.tsv');

for my $pair (@tables) {
  my ($pkg, $path) = @$pair;
  my ($h, $rows) = load_tsv($path);
  is($h, $header, "$pkg header");
  my $prev = '';
  my $sorted = 1;
  my $kinds_ok = 1;
  for my $line (@$rows) {
    my @c = split /\t/, $line, -1;
    my $key = join("\t", $c[0] // '', $c[2] // '', $c[1] // '');
    $sorted = 0 if $prev ne '' && $key lt $prev;
    $prev = $key;
    $kinds_ok = 0 unless ($c[1] // '') =~ /^(symbol|alphabet|text)$/;
  }
  ok($sorted, "$pkg is sorted by command/mode/kind");
  ok($kinds_ok, "$pkg kinds are symbol|alphabet|text");
  my $prov_path = File::Spec->catfile((File::Spec->splitpath($path))[1], 'provenance.json');
  ok(-f $prov_path, "$pkg provenance.json");
  if (-f $prov_path) {
    open my $pfh, '<:raw', $prov_path or die "read $prov_path: $!";
    my $prov = JSON::PP->new->utf8->decode(do { local $/; <$pfh> });
    close $pfh;
    my $n = $prov->{rows} // ($prov->{table}{rows} // undef);
    is(scalar @$rows, $n, "$pkg row count matches provenance") if defined $n;
  }
}

# Spot checks from the extract inventory.
sub find_row {
  my ($rows, $cmd) = @_;
  for my $line (@$rows) {
    my @c = split /\t/, $line, -1;
    return \@c if $c[0] eq $cmd;
  }
  return;
}

my %by_pkg = map { $_->[0] => $_->[1] } @tables;
if ($by_pkg{amssymb}) {
  my ($h, $rows) = load_tsv($by_pkg{amssymb});
  my $r = find_row($rows, '\\varnothing');
  ok($r, '\\varnothing in amssymb');
  is($r->[3], 'U+2205', '\\varnothing codepoint') if $r;
}
if ($by_pkg{extarrows} && $by_pkg{extpfeil}) {
  my ($h1, $a) = load_tsv($by_pkg{extarrows});
  my ($h2, $b) = load_tsv($by_pkg{extpfeil});
  my $x = find_row($a, '\\lx@stretchy@longequal');
  my $y = find_row($b, '\\lx@stretchy@longequal');
  ok($x && $y, '\\lx@stretchy@longequal in extarrows and extpfeil');
  is($x->[3], $y->[3], 'xlongequal stretchy codepoints agree') if $x && $y;
  is($x->[6], $y->[6], 'xlongequal stretchy roles agree') if $x && $y;
}
if ($by_pkg{_kernel}) {
  my ($h, $rows) = load_tsv($by_pkg{_kernel});
  ok(find_row($rows, '\\alpha'),  'kernel has \\alpha');
  ok(find_row($rows, '\\leq'),    'kernel has \\leq');
  my $scr = find_row($rows, '\\mathscr{}') || find_row($rows, '\\mathscr');
  ok($scr, 'kernel has \\mathscr');
}

done_testing();
