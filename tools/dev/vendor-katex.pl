#!/usr/bin/env perl
# tools/dev/vendor-katex.pl
#
# Copy a pinned KaTeX clone into lib-katex/ and derive the reference tables.
# The engine never reads this root. Bindings never carry KaTeX names.
#
#   perl tools/dev/vendor-katex.pl --clone=<path>
#   perl tools/dev/vendor-katex.pl --restore --clone=<path>
#   perl tools/dev/vendor-katex.pl --derive
#   perl tools/dev/vendor-katex.pl --check
#
# --clone refuses a clone that is not at a tag with a clean tree.
# --restore requires --clone at provenance's tag and SHA; cloned_from is telemetry.
# Provenance is rewritten only when a file hash or the pin changed.

use strict;
use warnings;
use FindBin;
use Getopt::Long;
use File::Spec;
use File::Path qw(make_path);
use File::Copy qw(copy);
use File::Find;
use File::Basename qw(dirname);
use Digest::SHA qw(sha256_hex);
use Encode qw(encode_utf8 decode_utf8);
use JSON::PP;
use POSIX qw(strftime);

my $root = File::Spec->rel2abs(File::Spec->catdir($FindBin::RealBin, '..', '..'));
my $katex_root = File::Spec->catdir($root, 'lib-katex');
my $derived_dir = File::Spec->catdir($katex_root, 'derived');
my $prov_path = File::Spec->catfile($katex_root, 'provenance.json');

my %opt = (clone => undef, restore => 0, derive => 0, check => 0, quiet => 0);
GetOptions(\%opt, 'clone=s', 'restore', 'derive', 'check', 'quiet') or die usage();

sub usage {
  return "Usage: $0 --clone=<path>\n"
    . "       $0 --restore --clone=<path>\n"
    . "       $0 --derive\n"
    . "       $0 --check\n"; }

sub say_ { print STDERR "vendor-katex: @_\n" unless $opt{quiet}; }

my $json = JSON::PP->new->utf8->canonical->pretty;

my %GROUP_ID = (
  accent  => 'accent-token',
  bin     => 'bin',
  close   => 'close',
  inner   => 'inner',
  mathord => 'mathord',
  op      => 'op-token',
  open    => 'open',
  punct   => 'punct',
  rel     => 'rel',
  spacing => 'spacing',
  textord => 'textord',
);

my $n_modes = 0;
$n_modes++ if $opt{clone} && !$opt{restore};
$n_modes++ if $opt{restore};
$n_modes++ if $opt{derive};
$n_modes++ if $opt{check};
die "vendor-katex: choose one of --clone, --restore --clone, --derive, --check\n"
  if $n_modes != 1;
die "vendor-katex: --restore requires --clone=<path>\n"
  if $opt{restore} && !$opt{clone};

if ($opt{check}) {
  exit(run_check() ? 0 : 1); }
if ($opt{derive}) {
  derive_tables() or exit 1;
  exit 0; }
if ($opt{restore}) {
  restore_from_clone($opt{clone}) or exit 1;
  exit 0; }
vendor_from_clone($opt{clone}) or exit 1;
exit 0;

#----------------------------------------------------------------------
# Clone inspection
#----------------------------------------------------------------------

sub git {
  my ($dir, @args) = @_;
  my @cmd = ('git', '-C', $dir, @args);
  open my $fh, '-|', @cmd or die "vendor-katex: cannot run git: $!\n";
  local $/;
  my $out = <$fh> // '';
  close $fh;
  return ($? >> 8, $out); }

sub inspect_clone {
  my ($clone) = @_;
  die "vendor-katex: --clone path does not exist: $clone\n" unless -d $clone;
  my ($st, $tag) = git($clone, 'describe', '--tags', '--exact-match');
  chomp $tag;
  die "vendor-katex: clone is not at an exact tag (git describe --tags --exact-match)\n"
    if $st || !length($tag);
  my ($st2, $sha) = git($clone, 'rev-parse', 'HEAD');
  chomp $sha;
  die "vendor-katex: cannot read clone HEAD\n" if $st2 || $sha !~ /^[0-9a-f]{40}$/;
  my ($st3, $porc) = git($clone, 'status', '--porcelain');
  die "vendor-katex: cannot read git status of the clone\n" if $st3;
  $porc =~ s/\s+\z//;
  die "vendor-katex: clone working tree is not clean\n" if length($porc);
  return ($tag, $sha); }

#----------------------------------------------------------------------
# Copy list
#----------------------------------------------------------------------

sub copy_rel_paths {
  my ($clone) = @_;
  my @rel = qw(
    LICENSE
    package.json
    src/symbols.ts
    src/macros.ts
    src/unicodeAccents.js
    src/unicodeScripts.ts
  );
  for my $sub (qw(src/functions src/environments)) {
    my $dir = File::Spec->catdir($clone, split('/', $sub));
    next unless -d $dir;
    find({
        wanted => sub {
          return unless -f $_ && /\.ts\z/;
          my $abs = $File::Find::name;
          my $rel = File::Spec->abs2rel($abs, $clone);
          $rel =~ s{\\}{/}g;
          push @rel, $rel;
        },
        no_chdir => 1,
      },
      $dir);
  }
  return sort @rel; }

sub copy_sources {
  my ($clone) = @_;
  my %files;
  for my $rel (copy_rel_paths($clone)) {
    my $src = File::Spec->catfile($clone, split('/', $rel));
    die "vendor-katex: missing $rel in clone\n" unless -f $src;
    my $dst = File::Spec->catfile($katex_root, split('/', $rel));
    make_path(dirname($dst));
    copy($src, $dst) or die "vendor-katex: copy $rel: $!\n";
    $files{$rel} = file_sha256($dst);
  }
  return \%files; }

sub file_sha256 {
  my ($path) = @_;
  open my $fh, '<:raw', $path or die "vendor-katex: read $path: $!\n";
  local $/;
  my $bytes = <$fh>;
  close $fh;
  return sha256_hex($bytes); }

sub read_utf8 {
  my ($path) = @_;
  open my $fh, '<:raw', $path or die "vendor-katex: read $path: $!\n";
  local $/;
  my $bytes = <$fh>;
  close $fh;
  return decode_utf8($bytes); }

sub posix_rel {
  my ($abs, $base) = @_;
  my $rel = File::Spec->abs2rel($abs, $base);
  $rel =~ s{\\}{/}g;
  return $rel; }

#----------------------------------------------------------------------
# TS string / list helpers
#----------------------------------------------------------------------

# Return (decoded, end_pos) starting at an opening quote in $s at $i.
# Decode TS escapes here so "\\tag" stays backslash-tag, not a TAB.
sub parse_ts_string_at {
  my ($s, $i) = @_;
  my $q = substr($s, $i, 1);
  return unless $q eq '"' || $q eq "'";
  my $j = $i + 1;
  my $out = '';
  while ($j < length($s)) {
    my $c = substr($s, $j, 1);
    if ($c eq '\\' && $j + 1 < length($s)) {
      my $n = substr($s, $j + 1, 1);
      if ($n eq 'u' && substr($s, $j + 2, 4) =~ /^[0-9a-fA-F]{4}$/) {
        $out .= chr(hex(substr($s, $j + 2, 4)));
        $j += 6;
        next;
      }
      if ($n eq 'x' && substr($s, $j + 2, 2) =~ /^[0-9a-fA-F]{2}$/) {
        $out .= chr(hex(substr($s, $j + 2, 2)));
        $j += 4;
        next;
      }
      $out .= "\n" if $n eq 'n';
      $out .= "\t" if $n eq 't';
      $out .= "\r" if $n eq 'r';
      $out .= $n   if $n ne 'n' && $n ne 't' && $n ne 'r';
      $j += 2;
      next;
    }
    if ($c eq $q) {
      return ($out, $j + 1);
    }
    $out .= $c;
    $j++;
  }
  return; }

sub skip_ws {
  my ($s, $i) = @_;
  while ($i < length($s)) {
    my $c = substr($s, $i, 1);
    if ($c =~ /\s/) { $i++; next; }
    if (substr($s, $i, 2) eq '//') {
      $i = index($s, "\n", $i);
      $i = length($s) if $i < 0;
      $i++ if $i < length($s);
      next;
    }
    if (substr($s, $i, 2) eq '/*') {
      my $end = index($s, '*/', $i + 2);
      last if $end < 0;
      $i = $end + 2;
      next;
    }
    last;
  }
  return $i; }

# Concatenated string literals: "a" + "b"
sub parse_concat_string_at {
  my ($s, $i) = @_;
  $i = skip_ws($s, $i);
  my ($piece, $j) = parse_ts_string_at($s, $i);
  return unless defined $piece;
  my $acc = $piece;
  $i = $j;
  while (1) {
    $i = skip_ws($s, $i);
    last unless substr($s, $i, 1) eq '+';
    $i = skip_ws($s, $i + 1);
    my ($next, $nj) = parse_ts_string_at($s, $i);
    last unless defined $next;
    $acc .= $next;
    $i = $nj;
  }
  return ($acc, $i); }

sub parse_string_array_at {
  my ($s, $i) = @_;
  $i = skip_ws($s, $i);
  return unless substr($s, $i, 1) eq '[';
  $i++;
  my @items;
  while ($i < length($s)) {
    $i = skip_ws($s, $i);
    last if substr($s, $i, 1) eq ']';
    if (substr($s, $i, 1) eq ',') { $i++; next; }
    my ($str, $j) = parse_ts_string_at($s, $i);
    last unless defined $str;
    push @items, $str;
    $i = $j;
  }
  $i++ if substr($s, $i, 1) eq ']';
  return (\@items, $i); }

#----------------------------------------------------------------------
# Parsers
#----------------------------------------------------------------------

sub parse_symbols {
  my ($text) = @_;
  my @rows;
  my $i = 0;
  while ($text =~ /defineSymbol\(/g) {
    my $pos = pos($text);
    next if $-[0] >= 9 && substr($text, $-[0] - 9, 9) eq 'function ';
    my $s = substr($text, $pos);
    $s =~ s/^\s+//;
    my ($mode, $font, $group_id, $rest);
    if ($s =~ /^(math|text)\s*,\s*(main|ams)\s*,\s*(\w+)\s*,\s*/gc) {
      ($mode, $font, $group_id) = ($1, $2, $3);
      $rest = substr($s, pos($s));
    }
    else {
      next;
    }
    my $group = $GROUP_ID{$group_id} || $group_id;
    my ($replace, $p1) = parse_ts_string_at($rest, skip_ws($rest, 0));
    next unless defined $replace;
    my $p = skip_ws($rest, $p1);
    $p++ if substr($rest, $p, 1) eq ',';
    my ($name, $p2) = parse_ts_string_at($rest, skip_ws($rest, $p));
    next unless defined $name;
    my $accept = 0;
    $p = skip_ws($rest, $p2);
    if (substr($rest, $p, 1) eq ',') {
      $p = skip_ws($rest, $p + 1);
      $accept = 1 if substr($rest, $p, 4) eq 'true';
    }
    my $cp = '';
    $cp = sprintf('U+%04X', ord($replace)) if length($replace) == 1;
    push @rows, [$name, $mode, $font, $group, $cp, $accept ? '1' : '0'];
  }
  return \@rows; }

sub classify_macro {
  my ($expansion) = @_;
  return ('contextual', '', '') unless defined $expansion && length($expansion);
  if ($expansion =~ /^\\[A-Za-z@]+$/) {
    return ('alias', $expansion, $expansion);
  }
  if ($expansion =~ /\\operatorname\*?|\\mathop\b/) {
    return ('operator', $expansion, '');
  }
  return ('construct', $expansion, ''); }

sub parse_macros {
  my ($text) = @_;
  my @rows;
  my @residue;
  while ($text =~ /defineMacro\(/g) {
    my $pos = pos($text);
    my $rest = substr($text, $pos);
    my ($name, $p1) = parse_ts_string_at($rest, skip_ws($rest, 0));
    next unless defined $name;
    my $p = skip_ws($rest, $p1);
    $p++ if substr($rest, $p, 1) eq ',';
    $p = skip_ws($rest, $p);
    my ($kind, $expansion, $primary) = ('', '', '');
    if (substr($rest, $p, 8) eq 'function' || substr($rest, $p, 1) eq '(') {
      ($kind, $expansion, $primary) = ('contextual', '', '');
    }
    else {
      my ($exp, $p2) = parse_concat_string_at($rest, $p);
      if (defined $exp) {
        ($kind, $expansion, $primary) = classify_macro($exp);
      }
      else {
        push @residue, $name;
      }
    }
    push @rows, [$name, $kind, $expansion, $primary];
  }
  return (\@rows, \@residue); }

sub parse_op_ts {
  my ($text) = @_;
  my @rows;
  while ($text =~ /defineFunction\(\s*\{/g) {
    my $start = $-[0];
    my $next = index($text, 'defineFunction(', $start + 1);
    my $len = ($next >= 0 ? $next : length($text)) - $start;
    my $chunk = substr($text, $start, $len);
    next unless $chunk =~ /type:\s*"op"/;
    my $names_pos = index($chunk, 'names:');
    next if $names_pos < 0;
    my $arr_pos = index($chunk, '[', $names_pos);
    next if $arr_pos < 0;
    my ($names) = parse_string_array_at($chunk, $arr_pos);
    next unless $names && @$names;
    next if @$names == 1 && $names->[0] eq '\\mathop';
    my $limits = ($chunk =~ /limits:\s*true/) ? '1' : '0';
    my $symbol = ($chunk =~ /symbol:\s*true/) ? 1 : 0;
    my $kind = $symbol ? 'big' : 'named';
    for my $n (@$names) {
      push @rows, [$n, $kind, $limits, 'op.ts', ''];
    }
  }
  return \@rows; }

sub parse_fonts {
  my ($text) = @_;
  my @rows;
  my %alias = ('\\Bbb' => 'bb', '\\bold' => 'bf', '\\frak' => 'frak');
  my %alphabet = map { $_ => 1 } qw(
    \mathrm \mathit \mathbf \mathnormal \mathsfit
    \mathbb \mathcal \mathfrak \mathscr \mathsf \mathtt
    \Bbb \bold \frak
  );
  my %bold = map { $_ => 1 } qw(\boldsymbol \bm);
  my %legacy = map { $_ => 1 } qw(\rm \sf \tt \bf \it \cal);
  while ($text =~ /names:\s*\[/g) {
    my ($names) = parse_string_array_at($text, $-[0] + index(substr($text, $-[0]), '['));
    next unless $names;
    for my $cmd (@$names) {
      my ($font, $kind);
      if ($bold{$cmd}) {
        ($font, $kind) = ('boldsymbol', 'bold');
      }
      elsif ($legacy{$cmd}) {
        ($font, $kind) = ('math' . substr($cmd, 1), 'legacy');
      }
      elsif ($alphabet{$cmd}) {
        $kind = 'alphabet';
        if ($alias{$cmd}) {
          $font = $alias{$cmd};
        }
        else {
          $font = substr($cmd, 1);
          $font = 'bb'   if $cmd eq '\\mathbb';
          $font = 'cal'  if $cmd eq '\\mathcal';
          $font = 'frak' if $cmd eq '\\mathfrak';
          $font = 'scr'  if $cmd eq '\\mathscr';
          $font = 'sf'   if $cmd eq '\\mathsf';
          $font = 'tt'   if $cmd eq '\\mathtt';
          $font = 'rm'   if $cmd eq '\\mathrm';
          $font = 'it'   if $cmd eq '\\mathit';
          $font = 'bf'   if $cmd eq '\\mathbf';
        }
      }
      else {
        next;
      }
      push @rows, [$cmd, $font, $kind];
    }
  }
  return \@rows; }

sub parse_functions {
  my ($text, $source, $residue) = @_;
  my @rows;
  while ($text =~ /names:\s*\[/g) {
    my $at = $-[0];
    my $br = index($text, '[', $at);
    my ($names, $end) = parse_string_array_at($text, $br);
    unless ($names) {
      push @$residue, "$source:$at";
      next;
    }
    my $before = substr($text, 0, $at);
    my $df = rindex($before, 'defineFunction');
    my $de = rindex($before, 'defineEnvironment');
    my $kind = ($de > $df) ? 'environment' : 'function';
    for my $n (@$names) {
      push @rows, [$n, $kind, $source];
    }
  }
  return @rows; }

#----------------------------------------------------------------------
# Derive
#----------------------------------------------------------------------

sub katex_src {
  my ($rel) = @_;
  return File::Spec->catfile($katex_root, split('/', $rel)); }

sub write_tsv {
  my ($path, $header, $rows) = @_;
  my @sorted = sort {
    $a->[0] cmp $b->[0]
      || join("\t", @$a) cmp join("\t", @$b)
  } @$rows;
  make_path(dirname($path));
  open my $fh, '>:raw', $path or die "vendor-katex: write $path: $!\n";
  print $fh encode_utf8(join("\t", @$header) . "\n");
  for my $r (@sorted) {
    print $fh encode_utf8(join("\t", @$r) . "\n");
  }
  close $fh;
  return scalar @sorted; }

sub derive_tables {
  my $sym_path = katex_src('src/symbols.ts');
  my $mac_path = katex_src('src/macros.ts');
  my $op_path  = katex_src('src/functions/op.ts');
  my $font_path = katex_src('src/functions/font.ts');
  for my $p ($sym_path, $mac_path, $op_path, $font_path) {
    die "vendor-katex: missing vendored source $p (run --clone or --restore)\n"
      unless -f $p;
  }
  make_path($derived_dir);

  my $symbols = parse_symbols(read_utf8($sym_path));
  my ($macros, $macro_residue) = parse_macros(read_utf8($mac_path));
  my $ops = parse_op_ts(read_utf8($op_path));
  my $fonts = parse_fonts(read_utf8($font_path));

  my %op_seen;
  my @op_rows;
  for my $r (@$ops) {
    next if $op_seen{ $r->[0] }++;
    push @op_rows, $r;
  }
  for my $r (@$macros) {
    next unless $r->[1] eq 'operator';
    next if $op_seen{ $r->[0] }++;
    push @op_rows, [$r->[0], 'macro', '1', 'macros.ts', $r->[2]];
  }

  my @fn_rows;
  my @fn_residue;
  my @fn_dirs = (
    File::Spec->catdir($katex_root, 'src', 'functions'),
    File::Spec->catdir($katex_root, 'src', 'environments'),
  );
  for my $dir (@fn_dirs) {
    next unless -d $dir;
    find({
        wanted => sub {
          return unless -f $_ && /\.ts\z/;
          my $abs = $File::Find::name;
          my $rel = posix_rel($abs, $katex_root);
          my $text = read_utf8($abs);
          push @fn_rows, parse_functions($text, $rel, \@fn_residue);
        },
        no_chdir => 1,
      },
      $dir);
  }
  my %fn_seen;
  my @fn_uniq;
  for my $r (@fn_rows) {
    my $k = $r->[0] . "\t" . $r->[1];
    next if $fn_seen{$k}++;
    push @fn_uniq, $r;
  }

  my %counts;
  $counts{symbols} = write_tsv(
    File::Spec->catfile($derived_dir, 'katex-symbols.tsv'),
    [qw(name mode font group codepoint accept_unicode)], $symbols);
  $counts{macros} = write_tsv(
    File::Spec->catfile($derived_dir, 'katex-macros.tsv'),
    [qw(name kind expansion primary)], $macros);
  $counts{operators} = write_tsv(
    File::Spec->catfile($derived_dir, 'katex-operators.tsv'),
    [qw(name kind limits source expansion)], \@op_rows);
  $counts{fonts} = write_tsv(
    File::Spec->catfile($derived_dir, 'katex-fonts.tsv'),
    [qw(command font kind)], $fonts);
  $counts{functions} = write_tsv(
    File::Spec->catfile($derived_dir, 'katex-functions.tsv'),
    [qw(name kind source)], \@fn_uniq);

  say_ "derived symbols=$counts{symbols} macros=$counts{macros} "
    . "operators=$counts{operators} fonts=$counts{fonts} functions=$counts{functions}";
  if (@$macro_residue) {
    say_ "macro residue: " . join(', ', @$macro_residue);
  }
  if (@fn_residue) {
    say_ "function residue: " . join(', ', @fn_residue);
  }
  return (\%counts, $macro_residue, \@fn_residue); }

#----------------------------------------------------------------------
# Provenance
#----------------------------------------------------------------------

sub load_provenance {
  return unless -f $prov_path;
  open my $fh, '<:raw', $prov_path or return;
  local $/;
  my $bytes = <$fh>;
  close $fh;
  return eval { $json->decode($bytes) }; }

sub write_provenance {
  my ($data) = @_;
  make_path($katex_root);
  open my $fh, '>:raw', $prov_path or die "vendor-katex: write $prov_path: $!\n";
  print $fh $json->encode($data);
  close $fh; }

sub pin_unchanged {
  my ($old, $new) = @_;
  return 0 unless $old && $new;
  return 0 unless ($old->{tag}    || '') eq ($new->{tag}    || '');
  return 0 unless ($old->{commit} || '') eq ($new->{commit} || '');
  my $of = $old->{files}  || {};
  my $nf = $new->{files}  || {};
  return 0 unless join("\0", sort keys %$of) eq join("\0", sort keys %$nf);
  for my $k (keys %$nf) {
    return 0 unless ($of->{$k} || '') eq ($nf->{$k} || '');
  }
  return 1; }

#----------------------------------------------------------------------
# Commands
#----------------------------------------------------------------------

sub vendor_from_clone {
  my ($clone) = @_;
  $clone = File::Spec->rel2abs($clone);
  my ($tag, $sha) = inspect_clone($clone);
  say_ "clone $tag $sha";
  my $files = copy_sources($clone);
  my ($counts, $macro_res, $fn_res) = derive_tables();
  my $old = load_provenance();
  my $new = {
    source      => 'https://github.com/KaTeX/KaTeX',
    tag         => $tag,
    commit      => $sha,
    cloned_from => $clone,
    fetched_at  => strftime('%Y-%m-%dT%H:%M:%SZ', gmtime),
    files       => $files,
    counts      => $counts,
    residue     => {
      macros    => $macro_res || [],
      functions => $fn_res    || [],
    },
  };
  if (pin_unchanged($old, $new)) {
    $new->{fetched_at}  = $old->{fetched_at};
    $new->{cloned_from} = $old->{cloned_from};
    say_ "pin unchanged; provenance left as-is";
  }
  write_provenance($new);
  return 1; }

sub restore_from_clone {
  my ($clone) = @_;
  $clone = File::Spec->rel2abs($clone);
  my $prov = load_provenance() or die "vendor-katex: no $prov_path\n";
  my ($tag, $sha) = inspect_clone($clone);
  die "vendor-katex: clone tag $tag does not match provenance $prov->{tag}\n"
    unless $tag eq $prov->{tag};
  die "vendor-katex: clone SHA $sha does not match provenance $prov->{commit}\n"
    unless $sha eq $prov->{commit};
  my $files = copy_sources($clone);
  for my $rel (sort keys %{ $prov->{files} || {} }) {
    my $want = $prov->{files}{$rel};
    my $got  = $files->{$rel};
    die "vendor-katex: hash mismatch after restore: $rel\n"
      unless $got && $got eq $want;
  }
  say_ "restored " . scalar(keys %$files) . " files from $tag";
  return 1; }

sub run_check {
  my $prov = load_provenance() or die "vendor-katex: no $prov_path\n";
  my $ok = 1;
  my $files = $prov->{files} || {};
  my $present = 0;
  for my $rel (sort keys %$files) {
    my $path = katex_src($rel);
    next unless -f $path;
    $present++;
    my $got = file_sha256($path);
    if ($got ne $files->{$rel}) {
      print STDERR "vendor-katex: hash mismatch $rel\n";
      $ok = 0;
    }
  }
  say_ "checked $present/" . scalar(keys %$files) . " source files present";
  my %expect = (
    'katex-symbols.tsv'    => [qw(name mode font group codepoint accept_unicode)],
    'katex-macros.tsv'     => [qw(name kind expansion primary)],
    'katex-operators.tsv'  => [qw(name kind limits source expansion)],
    'katex-fonts.tsv'      => [qw(command font kind)],
    'katex-functions.tsv'  => [qw(name kind source)],
  );
  my $counts = $prov->{counts} || {};
  my %key = (
    'katex-symbols.tsv'   => 'symbols',
    'katex-macros.tsv'    => 'macros',
    'katex-operators.tsv' => 'operators',
    'katex-fonts.tsv'     => 'fonts',
    'katex-functions.tsv' => 'functions',
  );
  for my $name (sort keys %expect) {
    my $path = File::Spec->catfile($derived_dir, $name);
    unless (-f $path) {
      print STDERR "vendor-katex: missing $name\n";
      $ok = 0;
      next;
    }
    open my $fh, '<:raw', $path or die "vendor-katex: read $path: $!\n";
    my @lines = map { decode_utf8($_) } <$fh>;
    close $fh;
    chomp @lines;
    @lines = grep { length } @lines;
    unless (@lines) {
      print STDERR "vendor-katex: empty $name\n";
      $ok = 0;
      next;
    }
    my $header = shift @lines;
    my $want_h = join("\t", @{ $expect{$name} });
    if ($header ne $want_h) {
      print STDERR "vendor-katex: bad header $name\n";
      $ok = 0;
    }
    my $prev = '';
    for my $line (@lines) {
      if ($line lt $prev) {
        print STDERR "vendor-katex: unsorted $name\n";
        $ok = 0;
        last;
      }
      $prev = $line;
    }
    my $ckey = $key{$name};
    my $want_n = $counts->{$ckey};
    if (defined $want_n && $want_n != @lines) {
      print STDERR "vendor-katex: $name has " . scalar(@lines)
        . " rows, provenance counts.$ckey is $want_n\n";
      $ok = 0;
    }
  }
  return $ok; }

1;
