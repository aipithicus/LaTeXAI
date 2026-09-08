# -*- CPERL -*-
# lib-katex derived tables against provenance. Does not need the KaTeX clone;
# copied sources are gitignored and hashed only when present.
use strict;
use warnings;
use FindBin;
use File::Spec;
use Digest::SHA qw(sha256_hex);
use Encode qw(decode_utf8);
use JSON::PP;
use Test::More;

my $root = File::Spec->catdir($FindBin::Bin, '..');
my $katex = File::Spec->catdir($root, 'lib-katex');
my $derived = File::Spec->catdir($katex, 'derived');
my $prov_path = File::Spec->catfile($katex, 'provenance.json');

ok(-f $prov_path, 'provenance.json exists');
open my $pfh, '<:raw', $prov_path or die "read $prov_path: $!";
local $/;
my $prov = JSON::PP->new->utf8->decode(<$pfh>);
close $pfh;

is($prov->{source}, 'https://github.com/KaTeX/KaTeX', 'provenance source');
ok($prov->{tag}, 'provenance has tag');
ok($prov->{commit} && $prov->{commit} =~ /^[0-9a-f]{40}$/, 'provenance has full SHA');

my $files = $prov->{files} || {};
ok(scalar keys %$files, 'provenance lists copied files');
my $checked = 0;
for my $rel (sort keys %$files) {
  my $path = File::Spec->catfile($katex, split('/', $rel));
  next unless -f $path;
  $checked++;
  open my $fh, '<:raw', $path or die "read $path: $!";
  my $bytes = do { local $/; <$fh> };
  close $fh;
  is(sha256_hex($bytes), $files->{$rel}, "hash $rel");
}
ok(1, "hashed $checked sources present on disk");

sub load_tsv {
  my ($name) = @_;
  my $path = File::Spec->catfile($derived, $name);
  open my $fh, '<:raw', $path or die "read $path: $!";
  my $raw = do { local $/; <$fh> };
  close $fh;
  $raw =~ s/\r\n/\n/g;
  $raw =~ s/\n\z//;
  my @lines = split /\n/, decode_utf8($raw), -1;
  my $header = shift @lines;
  return ($header, \@lines);
}

my %headers = (
  'katex-symbols.tsv'   => "name\tmode\tfont\tgroup\tcodepoint\taccept_unicode",
  'katex-macros.tsv'    => "name\tkind\texpansion\tprimary",
  'katex-operators.tsv' => "name\tkind\tlimits\tsource\texpansion",
  'katex-fonts.tsv'     => "command\tfont\tkind",
  'katex-functions.tsv' => "name\tkind\tsource",
);
my %count_key = (
  'katex-symbols.tsv'   => 'symbols',
  'katex-macros.tsv'    => 'macros',
  'katex-operators.tsv' => 'operators',
  'katex-fonts.tsv'     => 'fonts',
  'katex-functions.tsv' => 'functions',
);

my %tables;
for my $name (sort keys %headers) {
  ok(-f File::Spec->catfile($derived, $name), "$name exists");
  my ($header, $rows) = load_tsv($name);
  is($header, $headers{$name}, "$name header");
  my $prev = '';
  my $sorted = 1;
  for my $line (@$rows) {
    $sorted = 0 if $line lt $prev;
    $prev = $line;
  }
  ok($sorted, "$name is sorted");
  my $ckey = $count_key{$name};
  is(scalar @$rows, $prov->{counts}{$ckey}, "$name row count matches provenance");
  $tables{$name} = $rows;
}

sub find_row {
  my ($rows, $name) = @_;
  for my $line (@$rows) {
    my @c = split /\t/, $line, -1;
    return \@c if $c[0] eq $name;
  }
  return;
}

my $lim = find_row($tables{'katex-operators.tsv'}, '\\lim');
ok($lim, '\\lim is an operator');
is($lim->[2], '1', '\\lim has limits') if $lim;

my $sin = find_row($tables{'katex-operators.tsv'}, '\\sin');
ok($sin, '\\sin is an operator');
is($sin->[2], '0', '\\sin has no limits') if $sin;

my $argmin = find_row($tables{'katex-operators.tsv'}, '\\argmin');
ok($argmin, '\\argmin is an operator');
is($argmin->[1], 'macro', '\\argmin is macro') if $argmin;

my $ne = find_row($tables{'katex-macros.tsv'}, '\\ne');
ok($ne, '\\ne is a macro');
is($ne->[1], 'alias', '\\ne is an alias') if $ne;
is($ne->[3], '\\neq', '\\ne primary is \\neq') if $ne;

my $dots = find_row($tables{'katex-macros.tsv'}, '\\dots');
ok($dots, '\\dots is a macro');
is($dots->[1], 'contextual', '\\dots is contextual') if $dots;

my $frac = find_row($tables{'katex-functions.tsv'}, '\\frac');
ok($frac, '\\frac is a function name');
is($frac->[1], 'function', '\\frac kind is function') if $frac;

my $matrix = find_row($tables{'katex-functions.tsv'}, 'matrix');
ok($matrix, 'matrix is a function-table name');
is($matrix->[1], 'environment', 'matrix kind is environment') if $matrix;

done_testing();
