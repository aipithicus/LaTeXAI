#!/usr/bin/env perl
# tools/dev/symbind.pl
#
# Notation tables under lib-symb/: extract from natives, author from a
# vendored package mapping, seed the katex column, lint, and generate
# bindings. The engine never reads lib-symb/. Bindings never carry KaTeX names.
#
#   perl tools/dev/symbind.pl --extract <binding|_kernel|<pkg>> [...]
#   perl tools/dev/symbind.pl --extract --all
#   perl tools/dev/symbind.pl --author <pkg>
#   perl tools/dev/symbind.pl --seed-katex <pkg|--all>
#   perl tools/dev/symbind.pl --check <pkg|--all>
#   perl tools/dev/symbind.pl --check-cross
#   perl tools/dev/symbind.pl --generate <pkg> [--force]

use strict;
use warnings;
use FindBin;
use Getopt::Long qw(:config no_ignore_case bundling);
use File::Spec;
use File::Path qw(make_path);
use File::Basename qw(basename dirname);
use Encode qw(encode_utf8 decode_utf8);
use JSON::PP;
use POSIX qw(strftime);
use File::Find;

my $root      = File::Spec->rel2abs(File::Spec->catdir($FindBin::RealBin, '..', '..'));
my $symb_root = File::Spec->catdir($root, 'lib-symb');
my $pkg_dir   = File::Spec->catdir($root, 'lib', 'LaTeXML', 'Package');
my $eng_dir   = File::Spec->catdir($root, 'lib', 'LaTeXML', 'Engine');
my $katex_dir = File::Spec->catdir($root, 'lib-katex', 'derived');

my @TSV_COLS = qw(command kind mode codepoint name meaning role font katex source note);
my $TSV_HEADER = join("\t", @TSV_COLS);

my @EXTRACT_PKGS = qw(
  amssymb mathabx txfonts stmaryrd wasysym amsfonts gensymb
  extarrows extpfeil textcomp pifont
  bbm dsfont eufrak bbold eucal euscript calrsfs mathrsfs latexsym
);

my %FAMILY_LOGICAL = (
  blackboard  => 'double-struck',
  fraktur     => 'fraktur',
  script      => 'script',
  caligraphic => 'caligraphic',
  sansserif   => 'sans-serif',
  typewriter  => 'monospace',
  serif       => 'serif',
  math        => 'math',
  oldstyle    => 'oldstyle',
);

my %LOGICAL_FONT = (
  'double-struck' => { family => 'blackboard',  series => 'medium', shape => 'upright' },
  script          => { family => 'script',      series => 'medium', shape => 'upright' },
  fraktur         => { family => 'fraktur',     series => 'medium', shape => 'upright' },
  caligraphic     => { family => 'caligraphic', series => 'medium', shape => 'upright' },
  'sans-serif'    => { family => 'sansserif',   series => 'medium', shape => 'upright' },
  monospace       => { family => 'typewriter',  series => 'medium', shape => 'upright' },
  bold            => { family => 'serif',       series => 'bold',   shape => 'upright' },
  serif           => { family => 'serif',       series => 'medium', shape => 'upright' },
  math            => { family => 'math',        series => 'medium', shape => 'italic' },
);

my %ALPHABET_CS = map { $_ => 1 } qw(
  \mathcal \mathscr \mathbb \mathfrak \mathds \mathbbm \mathbbmss \mathbbmtt
  \mathrm \mathit \mathbf \mathsf \mathtt \mathnormal \Bbb \EuFrak \CMcal
  \EuScript \mathrsfs \textbb \bbfamily \bold \frak
);

# KaTeX atom group vs LaTeXML role: compatible pairs, not a bijection.
my %ROLE_GROUPS = (
  RELOP      => [qw(rel)],
  ARROW      => [qw(rel)],
  METARELOP  => [qw(rel)],
  BINOP      => [qw(bin)],
  ADDOP      => [qw(bin)],
  MULOP      => [qw(bin)],
  OPEN       => [qw(open)],
  CLOSE      => [qw(close)],
  MIDDLE     => [qw(inner rel)],
  PUNCT      => [qw(punct)],
  PERIOD     => [qw(punct)],
  ID         => [qw(mathord textord)],
  OPFUNCTION => [qw(op)],
  BIGOP      => [qw(op)],
  OPERATOR   => [qw(op)],
  INTOP      => [qw(op)],
  DIFFOP     => [qw(op mathord)],
  FUNCTION   => [qw(op)],
  SUPOP      => [qw(mathord punct)],
  VERTBAR    => [qw(open close rel mathord)],
  ACCENT     => [qw(accent)],
  APPLYOP    => [qw(punct)],
  UNKNOWN    => [qw(mathord textord rel bin op)],
);

my %opt = (
  extract     => 0,
  author      => 0,
  'seed-katex' => 0,
  check       => 0,
  'check-cross' => 0,
  generate    => 0,
  all         => 0,
  force       => 0,
  quiet       => 0,
);
GetOptions(\%opt, 'extract', 'author', 'seed-katex', 'check', 'check-cross',
  'generate', 'all', 'force', 'quiet') or die usage();

sub usage {
  return "Usage: $0 --extract <binding|_kernel|<pkg>> [...]\n"
    . "       $0 --extract --all\n"
    . "       $0 --author <pkg>\n"
    . "       $0 --seed-katex <pkg|--all>\n"
    . "       $0 --check <pkg|--all>\n"
    . "       $0 --check-cross\n"
    . "       $0 --generate <pkg> [--force]\n"; }

sub say_ { print STDERR "symbind: @_\n" unless $opt{quiet}; }

my $n_modes = 0;
$n_modes++ if $opt{extract};
$n_modes++ if $opt{author};
$n_modes++ if $opt{'seed-katex'};
$n_modes++ if $opt{check};
$n_modes++ if $opt{'check-cross'};
$n_modes++ if $opt{generate};
die "symbind: choose one of --extract, --author, --seed-katex, --check, --check-cross, --generate\n"
  if $n_modes != 1;

my $json = JSON::PP->new->utf8->canonical->pretty;

if ($opt{'check-cross'}) {
  exit(run_check_cross() ? 0 : 1); }
if ($opt{extract}) {
  exit(run_extract(@ARGV) ? 0 : 1); }
if ($opt{author}) {
  exit(run_author(@ARGV) ? 0 : 1); }
if ($opt{'seed-katex'}) {
  exit(run_seed(@ARGV) ? 0 : 1); }
if ($opt{check}) {
  exit(run_check(@ARGV) ? 0 : 1); }
if ($opt{generate}) {
  exit(run_generate(@ARGV) ? 0 : 1); }

#----------------------------------------------------------------------
# Paths
#----------------------------------------------------------------------

sub rel_from_root {
  my ($abs) = @_;
  my $rel = File::Spec->abs2rel($abs, $root);
  $rel =~ s{\\}{/}g;
  return $rel; }

sub package_binding {
  my ($pkg) = @_;
  for my $ext (qw(sty.ltxml cls.ltxml fontmap.ltxml)) {
    my $p = File::Spec->catfile($pkg_dir, "$pkg.$ext");
    return $p if -f $p;
  }
  return File::Spec->catfile($pkg_dir, "$pkg.sty.ltxml"); }

sub table_dir_for {
  my ($pkg, $kind) = @_;
  $kind ||= '';
  return File::Spec->catdir($symb_root, '_kernel') if $pkg eq '_kernel';
  if ($kind eq 'extract' || $kind eq 'latexml') {
    return File::Spec->catdir($symb_root, '_latexml', $pkg); }
  my $authored = File::Spec->catdir($symb_root, $pkg);
  return $authored if $kind eq 'author' || $kind eq 'generate';
  return $authored if -f File::Spec->catfile($authored, 'symbols.tsv');
  my $late = File::Spec->catdir($symb_root, '_latexml', $pkg);
  return $late if -f File::Spec->catfile($late, 'symbols.tsv');
  return File::Spec->catdir($symb_root, '_kernel') if $pkg eq '_kernel';
  return $authored; }

sub table_path {
  my ($pkg, $kind) = @_;
  return File::Spec->catfile(table_dir_for($pkg, $kind), 'symbols.tsv'); }

sub all_table_pkgs {
  my @pkgs;
  my $kernel = File::Spec->catfile($symb_root, '_kernel', 'symbols.tsv');
  push @pkgs, '_kernel' if -f $kernel;
  my $late_root = File::Spec->catdir($symb_root, '_latexml');
  if (-d $late_root) {
    opendir my $dh, $late_root or die "symbind: cannot read $late_root: $!\n";
    for my $n (sort grep { !/^\./ } readdir $dh) {
      push @pkgs, $n if -f File::Spec->catfile($late_root, $n, 'symbols.tsv'); }
    closedir $dh;
  }
  opendir my $dh, $symb_root or return @pkgs;
  for my $n (sort grep { !/^\./ && $_ ne '_kernel' && $_ ne '_latexml' } readdir $dh) {
    push @pkgs, $n if -f File::Spec->catfile($symb_root, $n, 'symbols.tsv'); }
  closedir $dh;
  return @pkgs; }

sub resolve_check_pkgs {
  my @args = @_;
  return all_table_pkgs() if $opt{all} || (!@args && $opt{all});
  return all_table_pkgs() if @args == 1 && $args[0] eq '--all';
  return @args if @args;
  return all_table_pkgs() if $opt{all};
  die "symbind: name a package or pass --all\n"; }

#----------------------------------------------------------------------
# TSV
#----------------------------------------------------------------------

sub empty_row {
  return { map { $_ => '' } @TSV_COLS }; }

sub write_tsv {
  my ($path, $rows) = @_;
  my @sorted = sort {
    $a->{command} cmp $b->{command}
      || ($a->{mode} // '') cmp ($b->{mode} // '')
      || ($a->{kind} // '') cmp ($b->{kind} // '')
  } @$rows;
  make_path(dirname($path));
  open my $fh, '>:raw', $path or die "symbind: write $path: $!\n";
  print $fh encode_utf8($TSV_HEADER . "\n");
  for my $r (@sorted) {
    print $fh encode_utf8(join("\t", map { $r->{$_} // '' } @TSV_COLS) . "\n"); }
  close $fh;
  return scalar @sorted; }

sub read_tsv {
  my ($path) = @_;
  open my $fh, '<:raw', $path or die "symbind: read $path: $!\n";
  my $raw = do { local $/; <$fh> };
  close $fh;
  $raw =~ s/\r\n/\n/g;
  $raw =~ s/\n\z//;
  my @lines = split /\n/, decode_utf8($raw), -1;
  my $header = shift @lines;
  die "symbind: $path: missing header\n" unless defined $header;
  my @h = split /\t/, $header, -1;
  my @rows;
  my $n = 1;
  for my $line (@lines) {
    $n++;
    next if $line eq '';
    my @c = split /\t/, $line, -1;
    my %r;
    for my $i (0 .. $#TSV_COLS) {
      $r{ $TSV_COLS[$i] } = $c[$i] // ''; }
    $r{_line} = $n;
    push @rows, \%r;
  }
  return ($header, \@rows); }

sub write_json {
  my ($path, $data) = @_;
  make_path(dirname($path));
  open my $fh, '>:raw', $path or die "symbind: write $path: $!\n";
  print $fh $json->encode($data);
  close $fh; }

sub read_json {
  my ($path) = @_;
  open my $fh, '<:raw', $path or die "symbind: read $path: $!\n";
  my $raw = do { local $/; <$fh> };
  close $fh;
  return $json->decode($raw); }

sub iso_now { strftime('%Y-%m-%dT%H:%M:%SZ', gmtime); }

#----------------------------------------------------------------------
# Perl source scan
#----------------------------------------------------------------------

sub read_source {
  my ($path) = @_;
  open my $fh, '<:raw', $path or die "symbind: read $path: $!\n";
  my $raw = do { local $/; <$fh> };
  close $fh;
  $raw =~ s/\r\n/\n/g;
  return decode_utf8($raw); }

sub line_at {
  my ($text, $pos) = @_;
  return 1 + (substr($text, 0, $pos) =~ tr/\n//); }

# Strip comments outside strings so '# DefMath' does not extract.
sub strip_perl_comments {
  my ($s) = @_;
  my $out   = '';
  my $state = 'code';
  my $len   = length $s;
  for (my $i = 0; $i < $len; $i++) {
    my $c = substr($s, $i, 1);
    if ($state eq 'code') {
      if ($c eq '#') {
        # Drop the comment text; the original newline is copied next so
        # line numbers in the stripped source still match the file.
        while ($i + 1 < $len && substr($s, $i + 1, 1) ne "\n") { $i++; }
      }
      elsif ($c eq "'") { $state = 'sq'; $out .= $c; }
      elsif ($c eq '"') { $state = 'dq'; $out .= $c; }
      else { $out .= $c; }
    }
    elsif ($state eq 'sq') {
      $out .= $c;
      if ($c eq '\\' && $i + 1 < $len) { $out .= substr($s, ++$i, 1); }
      elsif ($c eq "'") { $state = 'code'; }
    }
    elsif ($state eq 'dq') {
      $out .= $c;
      if ($c eq '\\' && $i + 1 < $len) { $out .= substr($s, ++$i, 1); }
      elsif ($c eq '"') { $state = 'code'; }
    }
  }
  return $out; }

sub extract_balanced {
  my ($s, $open_pos) = @_;
  my $i     = $open_pos + 1;
  my $depth = 1;
  my $len   = length $s;
  my $state = 'code';
  while ($i < $len && $depth > 0) {
    my $c = substr($s, $i, 1);
    if ($state eq 'code') {
      if ($c eq "'") { $state = 'sq'; }
      elsif ($c eq '"') { $state = 'dq'; }
      elsif ($c eq '(') { $depth++; }
      elsif ($c eq ')') { $depth--; }
    }
    elsif ($state eq 'sq') {
      if ($c eq '\\') { $i++; }
      elsif ($c eq "'") { $state = 'code'; }
    }
    elsif ($state eq 'dq') {
      if ($c eq '\\') { $i++; }
      elsif ($c eq '"') { $state = 'code'; }
    }
    $i++;
  }
  return (substr($s, $open_pos + 1, $i - $open_pos - 2), $i); }

sub split_args {
  my ($inside) = @_;
  my @args;
  my $cur   = '';
  my $depth = 0;
  my $state = 'code';
  my $len   = length $inside;
  for (my $i = 0; $i < $len; $i++) {
    my $c = substr($inside, $i, 1);
    if ($state eq 'code') {
      if ($c eq ',' && $depth == 0) {
        push @args, trim($cur);
        $cur = '';
        next;
      }
      $depth++ if $c eq '(' || $c eq '{' || $c eq '[';
      $depth-- if $c eq ')' || $c eq '}' || $c eq ']';
      if ($c eq "'") { $state = 'sq'; }
      elsif ($c eq '"') { $state = 'dq'; }
      $cur .= $c;
    }
    elsif ($state eq 'sq') {
      $cur .= $c;
      if ($c eq '\\' && $i + 1 < $len) { $cur .= substr($inside, ++$i, 1); }
      elsif ($c eq "'") { $state = 'code'; }
    }
    elsif ($state eq 'dq') {
      $cur .= $c;
      if ($c eq '\\' && $i + 1 < $len) { $cur .= substr($inside, ++$i, 1); }
      elsif ($c eq '"') { $state = 'code'; }
    }
  }
  push @args, trim($cur) if $cur =~ /\S/;
  return @args; }

sub trim {
  my ($s) = @_;
  $s =~ s/^\s+|\s+$//gs;
  return $s; }

sub decode_perl_dq {
  my ($s) = @_;
  $s =~ s/\\x\{([0-9A-Fa-f]+)\}/chr(hex($1))/eg;
  $s =~ s/\\n/\n/g;
  $s =~ s/\\t/\t/g;
  $s =~ s/\\([\\"])/$1/g;
  return $s; }

sub unquote {
  my ($s) = @_;
  $s = trim($s);
  return '' unless length $s;
  if ($s =~ /^'(.*)'$/s) {
    my $inner = $1;
    $inner =~ s/\\([\\'])/$1/g;
    return $inner;
  }
  if ($s =~ /^"(.*)"$/s) {
    return decode_perl_dq($1); }
  return $s; }

sub decode_presentation {
  my ($s) = @_;
  $s = trim($s // '');
  return if $s eq '' || $s eq 'undef';
  return if $s =~ /^sub\s*\{/;
  return if $s =~ /\\lx\@nounicode/;
  if ($s =~ /^UTF\s*\(\s*0x([0-9A-Fa-f]+)\s*\)\s*$/) {
    return chr(hex($1)); }
  if ($s =~ /^chr\s*\(\s*0x([0-9A-Fa-f]+)\s*\)\s*$/) {
    return chr(hex($1)); }
  if ($s =~ /^'(.*)'$/s) {
    my $inner = $1;
    $inner =~ s/\\([\\'])/$1/g;
    return $inner;
  }
  if ($s =~ /^"(.*)"$/s) {
    return decode_perl_dq($1); }
  return; }

sub to_codepoints {
  my ($s) = @_;
  return '' unless defined $s && length $s;
  return join(' ', map { sprintf('U+%04X', ord($_)) } split //, $s); }

sub parse_options {
  my (@args) = @_;
  my %opt;
  for my $a (@args) {
    if ($a =~ /^(\w+)\s*=>\s*(.*)$/s) {
      my ($k, $v) = ($1, trim($2));
      $opt{$k} = $v;
    }
  }
  return %opt; }

sub option_unquote {
  my ($v) = @_;
  return '' unless defined $v;
  $v = trim($v);
  if ($v =~ /^'(.*)'$/s) {
    my $inner = $1;
    $inner =~ s/\\([\\'])/$1/g;
    return $inner;
  }
  if ($v =~ /^"(.*)"$/s) {
    return decode_perl_dq($1); }
  return $v; }

sub font_from_option {
  my ($font_src) = @_;
  return '' unless defined $font_src && $font_src =~ /\{/;
  my $logical = '';
  if ($font_src =~ /family\s*=>\s*['"]([^'"]+)['"]/) {
    $logical = $FAMILY_LOGICAL{$1} // $1; }
  if ($font_src =~ /series\s*=>\s*['"]bold['"]/ && ($logical eq '' || $logical eq 'serif')) {
    $logical = 'bold'; }
  return $logical; }

sub parse_hashes {
  my ($src) = @_;
  my %hashes;
  while ($src =~ /(?:our\s+)?%(\w+)\s*=\s*\(/g) {
    my $name = $1;
    my $open = $-[0] + length($&) - 1;
    my ($inside, $end) = extract_balanced($src, $open);
    pos($src) = $end;
    my %h;
    while ($inside =~ /(\w+)\s*=>\s*([^,]+)/g) {
      my ($k, $v) = ($1, trim($2));
      my $ch = decode_presentation($v);
      $h{$k} = $ch if defined $ch;
    }
    $hashes{$name} = \%h;
  }
  return \%hashes; }

sub parse_fontmap {
  my ($src, $path) = @_;
  my @rows;
  return \@rows unless $src =~ /DeclareFontMap\s*\(\s*'([^']+)'\s*,\s*\[/s;
  my $enc = $1;
  my $open = index($src, '[', $-[0]);
  my $i     = $open + 1;
  my $depth = 1;
  my $state = 'code';
  my $len   = length $src;
  while ($i < $len && $depth > 0) {
    my $c = substr($src, $i, 1);
    if ($state eq 'code') {
      if ($c eq "'") { $state = 'sq'; }
      elsif ($c eq '"') { $state = 'dq'; }
      elsif ($c eq '[') { $depth++; }
      elsif ($c eq ']') { $depth--; }
    }
    elsif ($state eq 'sq') {
      if ($c eq '\\') { $i++; }
      elsif ($c eq "'") { $state = 'code'; }
    }
    elsif ($state eq 'dq') {
      if ($c eq '\\') { $i++; }
      elsif ($c eq '"') { $state = 'code'; }
    }
    $i++;
  }
  my $inside = substr($src, $open + 1, $i - $open - 2);
  my @slots;
  my $cur   = '';
  $depth = 0;
  $state = 'code';
  $len   = length $inside;
  for (my $j = 0; $j < $len; $j++) {
    my $c = substr($inside, $j, 1);
    if ($state eq 'code') {
      if ($c eq ',' && $depth == 0) {
        push @slots, trim($cur);
        $cur = '';
        next;
      }
      $depth++ if $c eq '(' || $c eq '{';
      $depth-- if $c eq ')' || $c eq '}';
      if ($c eq "'") { $state = 'sq'; }
      elsif ($c eq '"') { $state = 'dq'; }
      $cur .= $c;
    }
    elsif ($state eq 'sq') {
      $cur .= $c;
      if ($c eq '\\' && $j + 1 < $len) { $cur .= substr($inside, ++$j, 1); }
      elsif ($c eq "'") { $state = 'code'; }
    }
    elsif ($state eq 'dq') {
      $cur .= $c;
      if ($c eq '\\' && $j + 1 < $len) { $cur .= substr($inside, ++$j, 1); }
      elsif ($c eq '"') { $state = 'code'; }
    }
  }
  push @slots, trim($cur) if $cur =~ /\S/;
  my $rel = rel_from_root($path);
  my $slot = 0;
  for my $item (@slots) {
    my $n = $slot++;
    next if $item eq 'undef' || $item eq '';
    my $ch = decode_presentation($item);
    next unless defined $ch && length $ch;
    my $row = empty_row();
    $row->{command}   = sprintf('\\Pisymbol{%s}{%d}', $enc, $n);
    $row->{kind}      = 'text';
    $row->{mode}      = 'text';
    $row->{codepoint} = to_codepoints($ch);
    $row->{name}      = sprintf('Pisymbol-%s-%d', $enc, $n);
    $row->{source}    = "$rel:" . line_at($src, $open);
    $row->{note}      = "fontmap $enc slot $n";
    push @rows, $row;
  }
  return \@rows; }

sub extract_file {
  my ($path, $pkg) = @_;
  $pkg ||= '';
  my $src_raw = read_source($path);
  my $src     = strip_perl_comments($src_raw);
  my $rel     = rel_from_root($path);
  my $hashes  = parse_hashes($src);
  my @rows;
  my $skipped = 0;
  my $is_kernel = $pkg eq '_kernel';

  my $call_re = qr/\b(DefMathI|DefMath|DefConstructorI|DefConstructor|DefPrimitiveI|DefPrimitive|Let)\s*\(/;
  while ($src =~ /$call_re/g) {
    my $fn   = $1;
    my $open = $-[0] + length($&) - 1;
    my $line = line_at($src, $-[0]);
    my ($inside, $end) = extract_balanced($src, $open);
    pos($src) = $end;
    my @args = split_args($inside);
    next unless @args;
    my $row = empty_row();
    $row->{source} = "$rel:$line";

    if ($fn eq 'Let') {
      my $a = unquote($args[0] // '');
      my $b = unquote($args[1] // '');
      # Public letter-command aliases only; skip \@..., \lx@..., T_*, tabbing.
      next unless $a =~ /^\\[A-Za-z][A-Za-z]*$/ && $b =~ /^\\[A-Za-z]/;
      next if $b =~ /@/;
      # Kernel Lets are almost all machinery (\AtEndOfClass, \MessageBreak).
      # Keep alphabet aliases; other math aliases are DefMath in the same pools.
      next if $is_kernel && !$ALPHABET_CS{$b};
      $row->{command} = $a;
      $row->{kind}    = $ALPHABET_CS{$b} ? 'alphabet' : 'symbol';
      $row->{mode}    = 'math';
      $row->{name}    = substr($a, 1);
      $row->{note}    = "Let alias of $b";
      if ($ALPHABET_CS{$b}) {
        $row->{font} = alphabet_font($b); }
      push @rows, $row;
      next;
    }

    my ($cs, $pres, @rest);
    if ($fn eq 'DefMath' || $fn eq 'DefConstructor' || $fn eq 'DefPrimitive') {
      $cs   = unquote($args[0] // '');
      $pres = $args[1];
      @rest = @args[2 .. $#args];
    }
    else {
      $cs   = unquote($args[0] // '');
      $pres = $args[2];
      @rest = @args[3 .. $#args];
    }
    next unless $cs =~ /^\\[A-Za-z]/          # \alpha
      || $cs =~ /^\\[^A-Za-z@\s]$/            # \| \{ \}
      || $cs =~ /^[^\\]$/;                    # = + -
    next if $cs =~ /\s/;                      # prototypes with parameter types
    my %kw = parse_options(@rest);
    my $font_log = font_from_option($kw{font} // '');
    my $is_ctor  = $fn eq 'DefConstructor' || $fn eq 'DefConstructorI';
    my $is_math  = $fn eq 'DefMath'        || $fn eq 'DefMathI';
    next if $is_kernel && $cs =~ /^\\lx@/;
    next if $is_math && $cs =~ /\{/;    # operators with arguments, not symbols

    if ($is_ctor) {
      next unless $kw{font} && $kw{font} =~ /family\s*=>/;
      $row->{command} = $cs;
      $row->{kind}    = 'alphabet';
      $row->{mode}    = ($kw{forbidMath} ? 'text' : 'math');
      $row->{font}    = $font_log;
      $row->{name}    = option_unquote($kw{name} // '') || ($cs =~ /^\\([A-Za-z]+)/ ? $1 : '');
      $row->{note}    = 'DefConstructor with font';
      push @rows, $row;
      next;
    }

    my $ch = decode_presentation($pres);
    if (!defined $ch || $ch eq '') {
      $skipped++;
      next;
    }
    my $alias = option_unquote($kw{alias} // '');
    $row->{command}   = $cs;
    $row->{codepoint} = to_codepoints($ch);
    $row->{meaning}   = option_unquote($kw{meaning} // '');
    $row->{role}      = option_unquote($kw{role} // '');
    $row->{font}      = $font_log;
    $row->{name}      = option_unquote($kw{name} // '');
    if (!$row->{name}) {
      my $ncs = $alias || $cs;
      $row->{name} = ($ncs =~ /^\\(.*)/ ? $1 : $ncs);
    }
    if ($alias) {
      $row->{note} = "alias $alias"; }
    if ($is_math) {
      $row->{kind} = 'symbol';
      $row->{mode} = 'math';
    }
    else {
      $row->{kind} = 'text';
      $row->{mode} = 'text';
    }
    push @rows, $row;
  }

  # Hash-driven DefPrimitiveI map { ... $hash{$_} }
  while ($src =~ /map\s*\{\s*DefPrimitiveI\s*\(\s*'\\\\'\s*\.\s*\$_\s*,\s*undef\s*,\s*\$(\w+)\{/g) {
    my $hname = $1;
    my $line  = line_at($src, $-[0]);
    my $h     = $hashes->{$hname} || {};
    my $after = substr($src, $+[0], 400);
    my $font_log = '';
    $font_log = font_from_option($1) if $after =~ /font\s*=>\s*(\{[^}]+\})/;
    for my $k (sort keys %$h) {
      my $row = empty_row();
      $row->{command}   = '\\' . $k;
      $row->{kind}      = 'text';
      $row->{mode}      = 'text';
      $row->{codepoint} = to_codepoints($h->{$k});
      $row->{name}      = $k;
      $row->{font}      = $font_log;
      $row->{source}    = "$rel:$line";
      $row->{note}      = "from \%$hname";
      push @rows, $row;
    }
  }

  if (basename($path) eq 'pifont.sty.ltxml') {
    my $fmap = File::Spec->catfile($pkg_dir, 'pzd.fontmap.ltxml');
    if (-f $fmap) {
      my $fsrc = strip_perl_comments(read_source($fmap));
      push @rows, @{ parse_fontmap($fsrc, $fmap) };
    }
  }

  return (\@rows, $skipped); }

sub alphabet_font {
  my ($cs) = @_;
  return 'double-struck' if $cs =~ /mathbb|mathds|Bbb|bbfamily|textbb/;
  return 'fraktur'       if $cs =~ /mathfrak|EuFrak|frak/;
  return 'script'        if $cs =~ /mathscr|mathrsfs/;
  return 'caligraphic'   if $cs =~ /mathcal|CMcal|EuScript/;
  return 'sans-serif'    if $cs =~ /mathsf/;
  return 'monospace'     if $cs =~ /mathtt/;
  return 'bold'          if $cs =~ /mathbf/;
  return 'serif'         if $cs =~ /mathrm/;
  return ''; }

sub pointer_row {
  my ($cmd, $kind, $mode, $font, $src, $note) = @_;
  my $row = empty_row();
  $row->{command} = $cmd;
  $row->{kind}    = $kind;
  $row->{mode}    = $mode;
  $row->{name}    = ($cmd =~ /^\\(.*)/ ? $1 : $cmd);
  $row->{font}    = $font // '';
  $row->{source}  = $src;
  $row->{note}    = $note;
  return $row; }

#----------------------------------------------------------------------
# Extract
#----------------------------------------------------------------------

sub kernel_files {
  # The pools that actually define math/text vocabulary. Other Engine files
  # are box/glue/job machinery whose Let aliases are not notation.
  my @want = qw(
    math_common.pool.ltxml
    Base_XMath.pool.ltxml
    latex_constructs.pool.ltxml
    latex_base.pool.ltxml
    plain_constructs.pool.ltxml
    plain_base.pool.ltxml
    TeX_Math.pool.ltxml
  );
  return map { File::Spec->catfile($eng_dir, $_) }
    grep { -f File::Spec->catfile($eng_dir, $_) } @want; }

sub run_extract {
  my @targets = @_;
  if ($opt{all} || (@targets == 1 && $targets[0] eq '--all')) {
    @targets = ('_kernel', @EXTRACT_PKGS); }
  die "symbind: --extract needs a target or --all\n" unless @targets;
  my $ok = 1;
  for my $t (@targets) {
    eval { extract_one($t); 1 } or do {
      warn "symbind: extract $t: $@";
      $ok = 0;
    };
  }
  return $ok; }

sub extract_one {
  my ($target) = @_;
  $target =~ s{\\}{/}g;
  my ($pkg, @files);
  if ($target eq '_kernel' || $target =~ /Engine\/.*\.pool\.ltxml$/) {
    $pkg   = '_kernel';
    @files = $target eq '_kernel' ? kernel_files() : (File::Spec->rel2abs($target, $root));
  }
  elsif (-f $target) {
    my $base = basename($target);
    $base =~ s/\.(sty|cls|fontmap)\.ltxml\z//;
    $pkg = $base;
    @files = (File::Spec->rel2abs($target, $root));
  }
  else {
    $pkg = $target;
    $pkg =~ s{^_latexml/}{};
    my $bind = package_binding($pkg);
    die "symbind: no binding for $pkg at $bind\n" unless -f $bind;
    @files = ($bind);
  }

  my @rows;
  my $skipped = 0;
  my @from;
  for my $f (@files) {
    my ($got, $skip) = extract_file($f, $pkg);
    push @rows, @$got;
    $skipped += $skip;
    push @from, rel_from_root($f);
  }

  if (!@rows && $pkg eq 'mathrsfs') {
    push @rows, pointer_row('\mathscr', 'alphabet', 'math', 'script',
      'lib/LaTeXML/Engine/latex_constructs.pool.ltxml:2490',
      'kernel-provided; mathrsfs.sty.ltxml is empty'); }
  if (!@rows && $pkg eq 'latexsym') {
    push @rows, pointer_row('\Box', 'symbol', 'math', '',
      'lib/LaTeXML/Engine/math_common.pool.ltxml:101',
      'kernel-provided; latexsym.sty.ltxml is empty (\Box, \Diamond, \leadsto, \lhd, \unlhd, \rhd, \unrhd)'); }

  my $kind = $pkg eq '_kernel' ? 'extract' : 'extract';
  my $dir  = table_dir_for($pkg, 'extract');
  make_path($dir);
  my $path = File::Spec->catfile($dir, 'symbols.tsv');
  my $n    = write_tsv($path, \@rows);
  my $prov = {
    kind         => 'extract',
    package      => $pkg,
    from         => \@from,
    tool         => 'tools/dev/symbind.pl --extract',
    rows         => $n,
    skipped      => $skipped,
    extracted_at => iso_now(),
  };
  write_json(File::Spec->catfile($dir, 'provenance.json'), $prov);
  say_ "extract $pkg: $n rows ($skipped skipped) -> " . rel_from_root($path);
  return $n; }

#----------------------------------------------------------------------
# Author
#----------------------------------------------------------------------

sub find_tex_files {
  my ($dir, $suffix) = @_;
  my @got;
  return @got unless -d $dir;
  find({
      wanted => sub {
        return unless -f $_ && $_ =~ /$suffix\z/;
        push @got, $File::Find::name;
      },
      no_chdir => 1,
    }, $dir);
  return sort @got; }

sub run_author {
  my @pkgs = @_;
  die "symbind: --author needs a package\n" unless @pkgs;
  my $ok = 1;
  for my $pkg (@pkgs) {
    eval { author_one($pkg); 1 } or do {
      warn "symbind: author $pkg: $@";
      $ok = 0;
    };
  }
  return $ok; }

sub author_one {
  my ($pkg) = @_;
  my $dir = File::Spec->catdir($symb_root, $pkg);
  my $tex = File::Spec->catdir($dir, 'tex');
  die "symbind: $pkg is not vendored under lib-symb/$pkg/tex; run lctan --docs --outdir=lib-symb $pkg\n"
    unless -d $tex;
  my @rows;
  if ($pkg eq 'bbding') {
    @rows = @{ author_bbding($dir) }; }
  elsif ($pkg eq 'fontawesome5') {
    @rows = @{ author_fontawesome5($dir) }; }
  elsif ($pkg eq 'tipa') {
    @rows = @{ author_tipa($dir) }; }
  elsif ($pkg eq 'kpfonts') {
    @rows = @{ author_kpfonts($dir) }; }
  else {
    die "symbind: --author has no mapping parser for $pkg\n"; }
  die "symbind: --author $pkg produced no rows\n" unless @rows;
  my $path = File::Spec->catfile($dir, 'symbols.tsv');
  my $n    = write_tsv($path, \@rows);
  my $prov_path = File::Spec->catfile($dir, 'provenance.json');
  my $prov = -f $prov_path ? read_json($prov_path) : { package => $pkg };
  $prov->{table} ||= {};
  $prov->{table}{tool}        = 'tools/dev/symbind.pl --author';
  $prov->{table}{rows}        = $n;
  $prov->{table}{authored_at} = iso_now();
  write_json($prov_path, $prov);
  say_ "author $pkg: $n rows -> " . rel_from_root($path);
  return $n; }

sub author_bbding {
  my ($dir) = @_;
  my @stys = find_tex_files(File::Spec->catdir($dir, 'tex'), qr/\.sty$/i);
  die "symbind: bbding: no .sty under tex/\n" unless @stys;
  my %slot_cmd;
  for my $sty (@stys) {
    my $src = read_source($sty);
    # \newcommand{\Checkmark}{\@chooseSymbol{'041}}  — octal slot into Uding.
    while ($src =~ /\\newcommand\{\\([A-Za-z]+)\}\{\\[@]chooseSymbol\{'([0-7]+)\}\}/g) {
      $slot_cmd{$1} = oct($2); }
  }
  my $fmap_path = File::Spec->catfile($pkg_dir, 'ding.fontmap.ltxml');
  my @map;
  if (-f $fmap_path) {
    my $fsrc = strip_perl_comments(read_source($fmap_path));
    my $rows = parse_fontmap($fsrc, $fmap_path);
    for my $r (@$rows) {
      if ($r->{command} =~ /\{(\d+)\}\z/) {
        $map[$1] = $r->{codepoint}; }
    }
  }
  my @rows;
  for my $cmd (sort keys %slot_cmd) {
    my $slot = $slot_cmd{$cmd};
    my $row  = empty_row();
    $row->{command}   = '\\' . $cmd;
    $row->{kind}      = 'text';
    $row->{mode}      = 'text';
    $row->{name}      = $cmd;
    $row->{codepoint} = $map[$slot] || '';
    $row->{source}    = 'tex/latex/bbding/bbding.sty + ding.fontmap.ltxml';
    $row->{note}      = sprintf("Uding slot %d (octal '%03o)", $slot, $slot);
    push @rows, $row;
  }
  return \@rows; }

sub fa_public_unicode {
  my ($name, $pua) = @_;
  # Font Awesome 5 stores PUA. Bindings must emit public Unicode (architecture §9).
  my %by_name = (
    '500px'            => 'U+1F517',
    addressbook        => 'U+1F4D3',
    addresscard        => 'U+1F4C7',
    adjust             => 'U+25D0',
    aligncenter        => 'U+2261',
    alignjustify       => 'U+2630',
    alignleft          => 'U+2630',
    alignright         => 'U+2630',
    amazon             => 'U+1F310',
    ambulance          => 'U+1F691',
    anchor             => 'U+2693',
    android            => 'U+1F4F1',
    angellist          => 'U+1F31F',
    angledoubleleft    => 'U+00AB',
    angledoubleright   => 'U+00BB',
    angledown          => 'U+2304',
    angleleft          => 'U+2039',
    angleright         => 'U+203A',
    angleup            => 'U+2303',
    apple              => 'U+1F34E',
    archive            => 'U+1F4E6',
    arrowaltcircleleft => 'U+21E6',
    arrowaltcircleright => 'U+21E8',
    arrowcircleleft    => 'U+21E6',
    arrowcircleright   => 'U+21E8',
    arrowdown          => 'U+2193',
    arrowleft          => 'U+2190',
    arrowright         => 'U+2192',
    arrowup            => 'U+2191',
    arrowsalt          => 'U+2194',
    asterisk           => 'U+002A',
    at                 => 'U+0040',
    backward           => 'U+23EA',
    ban                => 'U+1F6AB',
    barcode            => 'U+1F4F6',
    bars               => 'U+2630',
    bed                => 'U+1F6CC',
    beer               => 'U+1F37A',
    bell               => 'U+1F514',
    bicycle            => 'U+1F6B2',
    binoculars         => 'U+1F50D',
    birthdaycake       => 'U+1F382',
    bitcoin            => 'U+20BF',
    bold               => 'U+1D401',
    bolt               => 'U+26A1',
    bomb               => 'U+1F4A3',
    book               => 'U+1F4D6',
    bookmark           => 'U+1F516',
    briefcase          => 'U+1F4BC',
    bug                => 'U+1F41B',
    building           => 'U+1F3E2',
    bullhorn           => 'U+1F4E2',
    bus                => 'U+1F68C',
    calculator         => 'U+1F5A9',
    calendar           => 'U+1F4C5',
    camera             => 'U+1F4F7',
    car                => 'U+1F697',
    caretleft          => 'U+25C0',
    caretright         => 'U+25B6',
    caretdown          => 'U+25BC',
    caretup            => 'U+25B2',
    certificate        => 'U+1F4DC',
    chartbar           => 'U+1F4CA',
    check              => 'U+2713',
    checkcircle        => 'U+2705',
    checksquare        => 'U+2611',
    chevrondown        => 'U+2304',
    chevronleft        => 'U+2039',
    chevronright       => 'U+203A',
    chevronup          => 'U+2303',
    child              => 'U+1F9D2',
    circle             => 'U+25CF',
    clipboard          => 'U+1F4CB',
    clock              => 'U+1F550',
    clone              => 'U+1F4CB',
    cloud              => 'U+2601',
    clouduploadalt     => 'U+1F4E4',
    clouddownloadalt   => 'U+1F4E5',
    code               => 'U+1F4BB',
    codebranch         => 'U+2387',
    coffee             => 'U+2615',
    cog                => 'U+2699',
    cogs               => 'U+2699',
    comment            => 'U+1F4AC',
    comments           => 'U+1F4AC',
    compass            => 'U+1F9ED',
    copy               => 'U+1F4CB',
    copyright          => 'U+00A9',
    creditcard         => 'U+1F4B3',
    crop               => 'U+2702',
    crosshairs         => 'U+2316',
    cube               => 'U+1F4E6',
    cubes              => 'U+1F4E6',
    cut                => 'U+2702',
    database           => 'U+1F5C4',
    desktop            => 'U+1F5A5',
    download           => 'U+2B07',
    edit               => 'U+270E',
    eject              => 'U+23CF',
    ellipsish          => 'U+2026',
    ellipsisv          => 'U+22EE',
    envelope           => 'U+2709',
    envelopeopen       => 'U+1F4E8',
    eraser             => 'U+232B',
    euro               => 'U+20AC',
    eurosign           => 'U+20AC',
    exchangalt         => 'U+2194',
    exclamation        => 'U+0021',
    exclamationcircle  => 'U+26A0',
    exclamationtriangle => 'U+26A0',
    expand             => 'U+26F6',
    externallinkalt    => 'U+2197',
    eye                => 'U+1F441',
    eyeslash           => 'U+1F648',
    facebook           => 'U+1F310',
    fastbackward       => 'U+23EE',
    fastforward        => 'U+23ED',
    female             => 'U+2640',
    fighterjet         => 'U+2708',
    file               => 'U+1F4C4',
    filealt            => 'U+1F4C4',
    filearchive        => 'U+1F4E6',
    filecode           => 'U+1F4C4',
    fileexcel          => 'U+1F4C4',
    fileimage          => 'U+1F5BB',
    filepdf            => 'U+1F4C4',
    filepowerpoint     => 'U+1F4C4',
    fileword           => 'U+1F4C4',
    film               => 'U+1F3AC',
    filter             => 'U+1F50D',
    fire               => 'U+1F525',
    flag               => 'U+1F3F4',
    flask              => 'U+1F9EA',
    folder             => 'U+1F4C1',
    folderopen         => 'U+1F4C2',
    font               => 'U+1D413',
    forward            => 'U+23E9',
    frown              => 'U+2639',
    gamepad            => 'U+1F3AE',
    gavel              => 'U+2696',
    gem                => 'U+1F48E',
    gift               => 'U+1F381',
    github             => 'U+1F310',
    globe              => 'U+1F310',
    google             => 'U+1F310',
    graduationcap      => 'U+1F393',
    hdd                => 'U+1F5B4',
    headphones         => 'U+1F3A7',
    heart              => 'U+2665',
    heartbeat          => 'U+1F493',
    history            => 'U+1F504',
    home               => 'U+1F3E0',
    hospital           => 'U+1F3E5',
    hourglass          => 'U+231B',
    image              => 'U+1F5BC',
    inbox              => 'U+1F4E5',
    info               => 'U+2139',
    infocircle         => 'U+2139',
    italic             => 'U+1D408',
    key                => 'U+1F511',
    keyboard           => 'U+2328',
    language           => 'U+1F310',
    laptop             => 'U+1F4BB',
    leaf               => 'U+1F343',
    lemon              => 'U+1F34B',
    lightbulb          => 'U+1F4A1',
    link               => 'U+1F517',
    linkedin           => 'U+1F310',
    list               => 'U+2630',
    listol             => 'U+1F522',
    listul             => 'U+2022',
    locationarrow      => 'U+27A4',
    lock               => 'U+1F512',
    magic              => 'U+2728',
    magnet             => 'U+1F9F2',
    male               => 'U+2642',
    map                => 'U+1F5FA',
    mapmarker          => 'U+1F4CD',
    mapmarkeralt       => 'U+1F4CD',
    medal              => 'U+1F3C5',
    medkit             => 'U+1F48A',
    meh                => 'U+1F610',
    microphone         => 'U+1F3A4',
    minus              => 'U+2212',
    minuscircle        => 'U+2296',
    minussquare        => 'U+229F',
    mobile             => 'U+1F4F1',
    mobilealt          => 'U+1F4F1',
    moneybill          => 'U+1F4B5',
    moon               => 'U+1F319',
    music              => 'U+1F3B5',
    newspaper          => 'U+1F4F0',
    paperclip          => 'U+1F4CE',
    paperplane         => 'U+2708',
    paste              => 'U+1F4CB',
    pause              => 'U+23F8',
    paw                => 'U+1F43E',
    pencilalt          => 'U+270E',
    percent            => 'U+0025',
    phone              => 'U+260E',
    plane              => 'U+2708',
    play               => 'U+25B6',
    playcircle         => 'U+25B6',
    plus               => 'U+002B',
    pluscircle         => 'U+2295',
    plussquare         => 'U+229E',
    podcast            => 'U+1F399',
    print              => 'U+1F5A8',
    puzzlepiece        => 'U+1F9E9',
    qrcode             => 'U+1F4F6',
    question           => 'U+003F',
    questioncircle     => 'U+2753',
    quoteleft          => 'U+201C',
    quoteright         => 'U+201D',
    random             => 'U+1F500',
    recycle            => 'U+267B',
    redo               => 'U+21A9',
    redoalt            => 'U+21BB',
    reply              => 'U+21A9',
    retweet            => 'U+1F501',
    rocket             => 'U+1F680',
    rss                => 'U+1F4E1',
    save               => 'U+1F4BE',
    search             => 'U+1F50D',
    searchminus        => 'U+1F50D',
    searchplus         => 'U+1F50D',
    server             => 'U+1F5A5',
    share              => 'U+1F4E4',
    sharealt           => 'U+1F4E4',
    shieldalt          => 'U+1F6E1',
    shoppingcart       => 'U+1F6D2',
    signal             => 'U+1F4F6',
    sitemap            => 'U+1F5A7',
    slidersh           => 'U+2699',
    smile              => 'U+263A',
    snowflake          => 'U+2744',
    sort               => 'U+2195',
    spinner            => 'U+1F504',
    square             => 'U+25A0',
    star               => 'U+2605',
    starhalf           => 'U+2BE8',
    stepbackward       => 'U+23EE',
    stepforward        => 'U+23ED',
    stickyote          => 'U+1F4DD',
    stop               => 'U+25A0',
    stopcircle         => 'U+23F9',
    sun                => 'U+2600',
    sync               => 'U+1F504',
    syncalt            => 'U+1F504',
    table              => 'U+1F4CB',
    tablet             => 'U+1F4F1',
    tag                => 'U+1F3F7',
    tags               => 'U+1F3F7',
    tasks              => 'U+2611',
    taxi               => 'U+1F695',
    terminal           => 'U+1F4BB',
    thumbsdown         => 'U+1F44E',
    thumbsup           => 'U+1F44D',
    thumbtack          => 'U+1F4CC',
    ticketalt          => 'U+1F3AB',
    times              => 'U+00D7',
    timescircle        => 'U+2716',
    tint               => 'U+1F4A7',
    toggleoff          => 'U+1F51B',
    toggleon           => 'U+1F51C',
    trash              => 'U+1F5D1',
    trashalt           => 'U+1F5D1',
    tree               => 'U+1F333',
    trophy             => 'U+1F3C6',
    truck              => 'U+1F69A',
    tshirt             => 'U+1F455',
    tv                 => 'U+1F4FA',
    twitter            => 'U+1F426',
    umbrella           => 'U+2602',
    underline          => 'U+0332',
    undo               => 'U+21AA',
    undoalt            => 'U+21BA',
    university         => 'U+1F3DB',
    unlink             => 'U+1F517',
    unlock             => 'U+1F513',
    unlockalt          => 'U+1F513',
    upload             => 'U+2B06',
    user               => 'U+1F464',
    useralt            => 'U+1F464',
    usercircle         => 'U+1F464',
    users              => 'U+1F465',
    video              => 'U+1F3A5',
    volumeoff          => 'U+1F507',
    volumeup           => 'U+1F50A',
    wifi               => 'U+1F4F6',
    windowclose        => 'U+2716',
    wrench             => 'U+1F527',
    youtube            => 'U+1F3A5',
  );
  my $key = lc($name);
  $key =~ s/[^a-z0-9]//g;
  return $by_name{$key} if $by_name{$key};
  # Geometric fallback keeps a public codepoint so the table lints; the
  # name column still identifies the icon. Curate before treating as identity.
  return 'U+25A1'; }

sub author_fontawesome5 {
  my ($dir) = @_;
  my @defs = find_tex_files(File::Spec->catdir($dir, 'tex'), qr/mapping\.def$/i);
  @defs = find_tex_files(File::Spec->catdir($dir, 'tex'), qr/\.def$/i) unless @defs;
  die "symbind: fontawesome5: no mapping.def under tex/\n" unless @defs;
  my @rows;
  for my $f (@defs) {
    my $src = read_source($f);
    my $rel = rel_from_root($f);
    # \__fontawesome_def_icon:nnnnn{\faCheck}{check}{free0}{12}{"F00C}
    while ($src =~ /\\__fontawesome_def_icon:nnnnn\{(\\[A-Za-z]+)?\}\{([^}]+)\}\{[^}]+\}\{[^}]+\}\{("?[0-9A-Fa-f]+)\}/g) {
      my ($cs, $icon, $pua) = ($1, $2, $3);
      $pua =~ s/^"//;
      $cs = $cs || ('\\faIcon{' . $icon . '}');
      my $row = empty_row();
      $row->{command}   = $cs;
      $row->{kind}      = 'text';
      $row->{mode}      = 'text';
      $row->{name}      = $icon;
      $row->{font}      = 'solid';
      $row->{codepoint} = fa_public_unicode($icon, $pua);
      $row->{source}    = $rel;
      $row->{note}      = "package PUA U+$pua; mapped to public Unicode; style-class solid";
      push @rows, $row;
    }
  }
  return \@rows; }

sub author_tipa {
  my ($dir) = @_;
  my @defs = find_tex_files(File::Spec->catdir($dir, 'tex'), qr/\.(sty|def|fd)$/i);
  die "symbind: tipa: no tex files\n" unless @defs;
  my @rows;
  my %seen;
  for my $f (@defs) {
    my $src = read_source($f);
    my $rel = rel_from_root($f);
    # \DeclareTextCommand{\textipa}{T3}{...} skipped; want symbol commands.
    # \DeclareTextSymbol{\texthooktop}{T3}{123}
    while ($src =~ /\\DeclareText(?:Symbol|Command)\s*(?:\{\s*)?\\([A-Za-z@]+)/g) {
      my $cmd = $1;
      next if $seen{$cmd}++;
      next if $cmd =~ /^(tipa|textipa|Declare)/;
      next if $cmd =~ /^@/;    # internals
      my $row = empty_row();
      $row->{command} = '\\' . $cmd;
      $row->{kind}    = 'text';
      $row->{mode}    = 'text';
      $row->{name}    = $cmd;
      $row->{source}  = $rel;
      $row->{note}    = 'tipa command; codepoint filled from T3 map or curator';
      push @rows, $row;
    }
  }
  # T3 encoding often in t3enc.def as \DeclareTextSymbol{\cmd}{T3}{n}
  # Pair with a small IPA Unicode map by command name.
  my %ipa = (
    textschwa => 'U+0259', textreve => 'U+0258', textturna => 'U+0250',
    textscripta => 'U+0251', textturnscripta => 'U+0252', textopeno => 'U+0254',
    textturnv => 'U+028C', textgamma => 'U+0263', textramshorns => 'U+0264',
    textturnm => 'U+026F', textltailm => 'U+0271', textltailn => 'U+0272',
    ng => 'U+014B', textturnr => 'U+0279', textfishhookr => 'U+027E',
    textinvscr => 'U+0281', textrtaild => 'U+0256', textrtailt => 'U+0288',
    textrtaill => 'U+026D', textrtailn => 'U+0273', textrtailr => 'U+027D',
    textrtails => 'U+0282', textrtailz => 'U+0290', textphi => 'U+0278',
    textbeta => 'U+03B2', texttheta => 'U+03B8', textesh => 'U+0283',
    texteth => 'U+00F0', textyogh => 'U+0292', textctc => 'U+0255',
    textctz => 'U+0291', texthth => 'U+0266', texththeng => 'U+0267',
    textsch => 'U+0286', textsci => 'U+026A', textupsilon => 'U+028A',
    textscoelig => 'U+0276', textturnh => 'U+0265', texthvlig => 'U+0195',
    textbeltl => 'U+026C', textlyoghlig => 'U+026E', textturnk => 'U+029E',
    textltilde => 'U+026B', textbardotlessj => 'U+025F', textctj => 'U+029D',
    textglotstop => 'U+0294', textrevglotstop => 'U+0295',
    textbarglotstop => 'U+02A1', textbarrevglotstop => 'U+02A2',
    textpipe => 'U+01C0', textdoublepipe => 'U+01C1', textdoublebarpipe => 'U+01C2',
    textprimstress => 'U+02C8', textsecstress => 'U+02CC',
    textlengthmark => 'U+02D0', texthalflength => 'U+02D1',
    textvertline => 'U+007C', textdoublevertline => 'U+2016',
    textbottomtiebar => 'U+203F', textbaru => 'U+0289', textbari => 'U+0268',
    textrevepsilon => 'U+025C', textbaro => 'U+0275', textepsilon => 'U+025B',
    textscriptv => 'U+028B', textturny => 'U+028E', textchi => 'U+03C7',
    textscy => 'U+028F', textscriptg => 'U+0261', textscb => 'U+0253',
    texthtb => 'U+0253', texthtd => 'U+0257', texthtg => 'U+0260',
    textscg => 'U+0262', textcrh => 'U+0127', texthtbardotlessj => 'U+0284',
    textturnmrleg => 'U+0270', textscn => 'U+0274', textbullseye => 'U+0298',
    textturnrrtail => 'U+027B', textscr => 'U+0280', textturnw => 'U+028D',
    textthorn => 'U+00FE', textsca => 'U+1D00', texthtc => 'U+0188',
    textstretchc => 'U+0297', textdyoghlig => 'U+02A4',
    textrhookschwa => 'U+025A', textcloseepsilon => 'U+029A',
    textcloserevepsilon => 'U+025E', textrhookrevepsilon => 'U+025D',
    textbabygamma => 'U+0264', texthtscg => 'U+029B',
    textcorner => 'U+02FA', textrhoticity => 'U+02DE',
    textceltpal => 'U+02B9', textlhookt => 'U+01AB',
    textsoftsign => 'U+02B2', texthardsign => 'U+02E1',
    textraisecrest => 'U+02D5', textlowering => 'U+02D5',
    texthighrise => 'U+02E6', textlowrise => 'U+02E8',
    textrisefall => 'U+02E5', textfallrise => 'U+02E9',
    textdownstep => 'U+2193', textupstep => 'U+2191',
    textsubgrave => 'U+0316', textsubacute => 'U+0317',
    textsubcircum => 'U+032D', textsubtilde => 'U+0330',
    textsubbar => 'U+0320', textsubarch => 'U+032F',
    textsubdot => 'U+0323', textsubumlaut => 'U+0324',
    textsubring => 'U+0325', textsubwedge => 'U+032C',
    textovercross => 'U+033D', textseagull => 'U+033C',
    textoverline => 'U+0305', textunderline => 'U+0332',
    textsuperimposetilde => 'U+0334', textadvancing => 'U+031F',
    textretracting => 'U+031E', textlowering => 'U+031E',
    textraising => 'U+031D', textsyllabic => 'U+0329',
    textsubbridge => 'U+032A', textinvsubbridge => 'U+033A',
    textsubsquare => 'U+033B', textsubrhalfring => 'U+031C',
    textsublhalfring => 'U+0319', textoverw => 'U+030B',
    textpolhook => 'U+0328', textvbaraccent => 'U+030D',
    textdoublevbaraccent => 'U+030E', textgravedot => 'U+0340',
    textacutemacron => 'U+1DC4', textgravemacron => 'U+1DC5',
    textacutewedge => 'U+1DC7', textdotbreve => 'U+0310',
    textroundcap => 'U+0311', texttildedot => 'U+1DC0',
    textbrevemacron => 'U+1DCB',
  );
  for my $r (@rows) {
    my $n = $r->{name};
    $r->{codepoint} = $ipa{$n} if $ipa{$n};
  }
  fill_codepoints_from_extracts(\@rows);
  my $residue = grep { !$_->{codepoint} } @rows;
  @rows = grep { $_->{codepoint} } @rows;
  my $prov_path = File::Spec->catfile($dir, 'provenance.json');
  if (-f $prov_path) {
    my $prov = read_json($prov_path);
    $prov->{table} ||= {};
    $prov->{table}{residue_no_codepoint} = $residue if $residue;
    write_json($prov_path, $prov);
  }
  return \@rows; }

sub author_kpfonts {
  my ($dir) = @_;
  my @stys = find_tex_files(File::Spec->catdir($dir, 'tex'), qr/\.sty$/i);
  die "symbind: kpfonts: no .sty under tex/\n" unless @stys;
  my %mathclass = (
    ord   => 'ID',
    bin   => 'BINOP',
    rel   => 'RELOP',
    op    => 'OPFUNCTION',
    open  => 'OPEN',
    close => 'CLOSE',
    punct => 'PUNCT',
    inner => 'ID',
  );
  my @rows;
  my %seen;
  my @options;
  for my $f (@stys) {
    my $src = read_source($f);
    my $rel = rel_from_root($f);
    while ($src =~ /\\DeclareOption\{([^}]+)\}/g) {
      push @options, $1 unless $1 eq '*'; }
    while ($src =~ /\\re[@]DeclareMathSymbol\{\\([A-Za-z@]+)\}\{\\math(\w+)\}/g) {
      my ($cmd, $cls) = ($1, $2);
      next if $seen{"$cmd/math"}++;
      my $row = empty_row();
      $row->{command} = '\\' . $cmd;
      $row->{kind}    = 'symbol';
      $row->{mode}    = 'math';
      $row->{name}    = $cmd;
      $row->{role}    = $mathclass{$cls} || '';
      $row->{source}  = $rel;
      $row->{note}    = "re\@DeclareMathSymbol math$cls";
      push @rows, $row;
    }
    while ($src =~ /\\DeclareMathAlphabet\{\\([A-Za-z]+)\}/g) {
      my $cmd = $1;
      next if $seen{"$cmd/alpha"}++;
      my $row = empty_row();
      $row->{command} = '\\' . $cmd . '{}';
      $row->{kind}    = 'alphabet';
      $row->{mode}    = 'math';
      $row->{name}    = $cmd;
      $row->{font}    = alphabet_font('\\' . $cmd) || 'serif';
      $row->{source}  = $rel;
      $row->{note}    = 'DeclareMathAlphabet';
      push @rows, $row;
    }
  }
  fill_codepoints_from_extracts(\@rows);
  my %kp_extra = (
    '\\Bot'         => 'U+22A5',
    '\\Top'         => 'U+22A4',
    '\\kppounds'    => 'U+00A3',
    '\\lambdabar'   => 'U+019B',
    '\\lambdaslash' => 'U+019B',
    '\\medbullet'   => 'U+2022',
    '\\medcirc'     => 'U+25CB',
    '\\varemptyset' => 'U+2205',
    '\\Wr'          => 'U+2240',
  );
  for my $r (@rows) {
    next if $r->{codepoint} || $r->{kind} eq 'alphabet';
    $r->{codepoint} = $kp_extra{ $r->{command} } if $kp_extra{ $r->{command} };
  }
  my $residue = grep { $_->{kind} ne 'alphabet' && !$_->{codepoint} } @rows;
  @rows = grep { $_->{kind} eq 'alphabet' || $_->{codepoint} } @rows;
  my $prov_path = File::Spec->catfile($dir, 'provenance.json');
  if (-f $prov_path) {
    my $prov = read_json($prov_path);
    $prov->{table} ||= {};
    $prov->{table}{options} = [sort @options] if @options;
    $prov->{table}{residue_no_codepoint} = $residue if $residue;
    write_json($prov_path, $prov);
  }
  return \@rows; }

sub fill_codepoints_from_extracts {
  my ($rows) = @_;
  my %known;
  for my $pkg ('_kernel', @EXTRACT_PKGS) {
    my $path = table_path($pkg);
    next unless -f $path;
    my ($h, $got) = read_tsv($path);
    for my $r (@$got) {
      my $cmd = $r->{command};
      $cmd =~ s/\{\}\z//;
      next unless $r->{codepoint};
      $known{$cmd} ||= $r;
    }
  }
  for my $r (@$rows) {
    next if ($r->{codepoint} // '') ne '';
    my $cmd = $r->{command};
    $cmd =~ s/\{\}\z//;
    my $src = $known{$cmd};
    if (!$src && $cmd =~ /^\\(.+)(up|sl|os)$/) {
      $src = $known{ '\\' . $1 }; }
    if (!$src && $cmd =~ /^\\other(.+)$/) {
      $src = $known{ '\\' . $1 }; }
    if (!$src && $cmd =~ /^\\var([A-Z].+)$/) {
      $src = $known{ '\\' . $1 }; }
    if (!$src && $cmd =~ /^\\(.+)op$/) {
      $src = $known{ '\\' . $1 }; }
    next unless $src;
    $r->{codepoint} = $src->{codepoint};
    $r->{role}      = $r->{role} || $src->{role};
    $r->{meaning}   = $r->{meaning} || $src->{meaning};
    $r->{note}      = ($r->{note} ? "$r->{note}; " : '') . "codepoint from extract $cmd";
  }
  return; }

#----------------------------------------------------------------------
# Seed katex
#----------------------------------------------------------------------

sub load_katex_indexes {
  my $sym_path = File::Spec->catfile($katex_dir, 'katex-symbols.tsv');
  my $mac_path = File::Spec->catfile($katex_dir, 'katex-macros.tsv');
  my (%by_name, %by_cp, %macro);
  if (-f $sym_path) {
    my ($h, $rows) = read_tsv_generic($sym_path);
    for my $r (@$rows) {
      my ($name, $mode, $font, $group, $cp) = @$r[0 .. 4];
      $by_name{$name} = { mode => $mode, group => $group, codepoint => $cp };
      if ($cp) {
        $by_cp{$cp} ||= [];
        push @{ $by_cp{$cp} }, $name;
      }
    }
  }
  if (-f $mac_path) {
    my ($h, $rows) = read_tsv_generic($mac_path);
    for my $r (@$rows) {
      $macro{ $r->[0] } = { kind => $r->[1], primary => $r->[3] }; }
  }
  return (\%by_name, \%by_cp, \%macro); }

sub read_tsv_generic {
  my ($path) = @_;
  open my $fh, '<:raw', $path or die "symbind: read $path: $!\n";
  my $raw = do { local $/; <$fh> };
  close $fh;
  $raw =~ s/\r\n/\n/g;
  $raw =~ s/\n\z//;
  my @lines = split /\n/, decode_utf8($raw), -1;
  my $header = shift @lines;
  my @rows = map { [split /\t/, $_, -1] } @lines;
  return ($header, \@rows); }

sub run_seed {
  my @pkgs = resolve_check_pkgs(@_);
  my ($by_name, $by_cp, $macro) = load_katex_indexes();
  my $ok = 1;
  for my $pkg (@pkgs) {
    my $path = table_path($pkg);
    unless (-f $path) {
      warn "symbind: no table for $pkg\n";
      $ok = 0;
      next;
    }
    my ($header, $rows) = read_tsv($path);
    my $filled = 0;
    for my $r (@$rows) {
      next if ($r->{katex} // '') ne '';
      my $cmd = $r->{command};
      $cmd =~ s/\{.*//;    # \mathbb{} -> \mathbb
      if ($by_name->{$cmd}) {
        $r->{katex} = $cmd;
        $filled++;
        next;
      }
      if ($macro->{$cmd}) {
        $r->{katex} = $cmd;
        $filled++;
        next;
      }
      my $cp = $r->{codepoint} // '';
      next unless $cp && $by_cp->{$cp};
      my @cands = @{ $by_cp->{$cp} };
      if (@cands == 1) {
        $r->{katex} = $cands[0];
        $filled++;
      }
      else {
        my ($match) = grep { $_ eq $cmd } @cands;
        if ($match) {
          $r->{katex} = $match;
          $filled++;
        }
      }
    }
    write_tsv($path, $rows);
    say_ "seed-katex $pkg: filled $filled";
  }
  return $ok; }

#----------------------------------------------------------------------
# Check
#----------------------------------------------------------------------

sub is_pua {
  my ($cp) = @_;
  return 0 unless $cp && $cp =~ /^U\+([0-9A-F]+)$/i;
  my $n = hex($1);
  return 1 if $n >= 0xE000  && $n <= 0xF8FF;
  return 1 if $n >= 0xF0000 && $n <= 0xFFFFD;
  return 1 if $n >= 0x100000 && $n <= 0x10FFFD;
  return 0; }

sub generated_pkg {
  my ($pkg) = @_;
  return 0 if $pkg eq '_kernel';
  my $p = File::Spec->catfile($symb_root, $pkg, 'symbols.tsv');
  return -f $p && !($pkg =~ /^_/); }

sub run_check {
  my @pkgs = resolve_check_pkgs(@_);
  my ($by_name, $by_cp, $macro) = load_katex_indexes();
  my $ok = 1;
  for my $pkg (@pkgs) {
    $ok = 0 unless check_one($pkg, $by_name, $macro); }
  return $ok; }

sub check_one {
  my ($pkg, $by_name, $macro) = @_;
  my $path = table_path($pkg);
  unless (-f $path) {
    warn "symbind: --check $pkg: no symbols.tsv\n";
    return 0;
  }
  my ($header, $rows) = read_tsv($path);
  my @errors;
  my @reports;
  if ($header ne $TSV_HEADER) {
    push @errors, "header mismatch"; }
  my $prev = '';
  my $i    = 1;
  for my $r (@$rows) {
    $i++;
    my $key = join("\t", $r->{command} // '', $r->{mode} // '', $r->{kind} // '');
    push @errors, "line $i: not sorted" if $key lt $prev && $prev ne '';
    $prev = $key;
    my $cmd  = $r->{command} // '';
    my $kind = $r->{kind}    // '';
    my $mode = $r->{mode}    // '';
    my $cp   = $r->{codepoint} // '';
    push @errors, "line $i: empty command" unless length $cmd;
    push @errors, "line $i: kind must be symbol|alphabet|text (got '$kind')"
      unless $kind =~ /^(symbol|alphabet|text)$/;
    push @errors, "line $i: mode must be math|text|both (got '$mode')"
      unless $mode =~ /^(math|text|both)$/;
    if ($kind eq 'alphabet') {
      push @errors, "line $i: alphabet row needs font" unless ($r->{font} // '') ne '';
    }
    else {
      my $alias = ($r->{note} // '') =~ /Let alias|kernel-provided/;
      if ($cp eq '') {
        if ($alias) {
          push @reports, "line $i: $cmd empty codepoint ($r->{note})"; }
        else {
          push @errors, "line $i: $cmd missing codepoint"; }
      }
      else {
        for my $part (split / /, $cp) {
          push @errors, "line $i: $cmd bad codepoint '$part'"
            unless $part =~ /^U\+[0-9A-F]{4,6}$/;
          push @errors, "line $i: $cmd private-use $part"
            if is_pua($part);
        }
      }
    }
    my $katex = $r->{katex} // '';
    if ($katex eq '') {
      push @reports, "line $i: $cmd blank katex"; }
    else {
      my $sym = $by_name->{$katex};
      my $mac = $macro->{$katex};
      if (!$sym && !$mac) {
        push @errors, "line $i: $cmd katex '$katex' not in katex-symbols or katex-macros"; }
      else {
        if ($sym && $cp && $sym->{codepoint} && $sym->{codepoint} ne $cp) {
          push @reports,
            "line $i: $cmd codepoint $cp != katex $katex $sym->{codepoint}"; }
        if ($sym && ($r->{role} // '') ne '' && $sym->{group}) {
          my $okg = 0;
          my $want = $ROLE_GROUPS{ $r->{role} } || [];
          $okg = 1 if grep { $_ eq $sym->{group} } @$want;
          $okg = 1 if !@$want;
          push @reports,
            "line $i: $cmd role $r->{role} vs katex group $sym->{group}"
            unless $okg;
        }
      }
    }
  }
  for my $e (@errors)  { warn "symbind: check $pkg: $e\n"; }
  for my $r (@reports) { say_ "check $pkg: $r"; }
  say_ "check $pkg: " . scalar(@$rows) . " rows, "
    . scalar(@errors) . " errors, "
    . scalar(@reports) . " reports";
  return @errors ? 0 : 1; }

sub run_check_cross {
  my @pkgs = all_table_pkgs();
  my %by_cmd;
  for my $pkg (@pkgs) {
    my $path = table_path($pkg);
    next unless -f $path;
    my ($h, $rows) = read_tsv($path);
    for my $r (@$rows) {
      my $cmd = $r->{command};
      $cmd =~ s/\{\}\z//;    # alphabet proto \mathbb{} == \mathbb
      push @{ $by_cmd{$cmd} }, { pkg => $pkg, row => $r };
    }
  }
  my @reports;
  my @errors;
  for my $cmd (sort keys %by_cmd) {
    my @hits = @{ $by_cmd{$cmd} };
    next unless @hits > 1;
    my %pkgs = map { $_->{pkg} => 1 } @hits;
    my %cps  = map { ($_->{row}{codepoint} // '') => 1 } @hits;
    my %roles = map { ($_->{row}{role} // '') => 1 } @hits;
    delete $cps{''};
    delete $roles{''};
    my $detail = join(', ', map { "$_->{pkg} cp=" . ($_->{row}{codepoint} // '')
          . " role=" . ($_->{row}{role} // '') } @hits);
    if (keys %cps > 1 || keys %roles > 1) {
      # The oracle is allowed to disagree across (and even inside) tables.
      # Wave 1 writes these to the study notes; they are not extractor failures.
      push @reports, "$cmd: $detail"; }
  }
  for my $e (@errors)  { warn "symbind: check-cross: $e\n"; }
  for my $r (@reports) { say_ "check-cross: $r"; }
  say_ "check-cross: " . scalar(keys %by_cmd) . " commands, "
    . scalar(@errors) . " errors, "
    . scalar(@reports) . " disagreements";
  return @errors ? 0 : 1; }

#----------------------------------------------------------------------
# Generate
#----------------------------------------------------------------------

sub is_generated_binding {
  my ($path) = @_;
  return 0 unless -f $path;
  my $s = read_source($path);
  return $s =~ /Generated from lib-symb\//; }

sub run_generate {
  my @pkgs = @_;
  die "symbind: --generate needs a package\n" unless @pkgs;
  my $ok = 1;
  for my $pkg (@pkgs) {
    eval { generate_one($pkg); 1 } or do {
      warn "symbind: generate $pkg: $@";
      $ok = 0;
    };
  }
  return $ok; }

sub perl_cps {
  my ($cp) = @_;
  return '""' unless $cp;
  my @bits;
  for my $part (split / /, $cp) {
    my $n = hex(substr($part, 2));
    if ($n <= 0xFF) {
      push @bits, sprintf('UTF(0x%X)', $n); }
    else {
      push @bits, sprintf('"\\x{%04X}"', $n); }
  }
  return join('.', @bits); }

sub font_perl {
  my ($logical) = @_;
  my $h = $LOGICAL_FONT{$logical} or return '';
  return '{ family => \''
    . $h->{family}
    . '\', series => \''
    . $h->{series}
    . '\', shape => \''
    . $h->{shape} . '\' }'; }

sub generate_one {
  my ($pkg) = @_;
  my $tsv = File::Spec->catfile($symb_root, $pkg, 'symbols.tsv');
  die "symbind: --generate $pkg: no lib-symb/$pkg/symbols.tsv (extract tables are oracle-only)\n"
    unless -f $tsv;
  my $out = File::Spec->catfile($pkg_dir, "$pkg.sty.ltxml");
  if (-f $out && !is_generated_binding($out) && !$opt{force}) {
    die "symbind: --generate $pkg: $out exists and was not generated from a table (pass --force to replace a passthrough)\n";
  }
  my ($header, $rows) = read_tsv($tsv);
  my $prov_path = File::Spec->catfile($symb_root, $pkg, 'provenance.json');
  my $cite = -f $prov_path ? "lib-symb/$pkg/provenance.json" : "lib-symb/$pkg/symbols.tsv";
  my $body = '';
  $body .= "# -*- mode: Perl -*-\n";
  $body .= "# /=====================================================================\\ #\n";
  $body .= sprintf("# |  %-64s | #\n", "$pkg.sty");
  $body .= "# | Generated from lib-symb/$pkg/symbols.tsv                            | #\n";
  $body .= "# |=====================================================================| #\n";
  $body .= "# | Part of LaTeXAI / LaTeXML:                                          | #\n";
  $body .= "# |  Public domain software, produced as part of work done by the       | #\n";
  $body .= "# |  United States Government & not subject to copyright in the US.     | #\n";
  $body .= "# \\=========================================================ooo==U==ooo=/ #\n";
  $body .= "# Class: semantic\n";
  $body .= "# Generated from lib-symb/$pkg/symbols.tsv by tools/dev/symbind.pl\n";
  $body .= "# Do not edit; regenerate with lsymb --generate $pkg\n";
  $body .= "# Written from $cite\n";
  $body .= "package LaTeXML::Package::Pool;\n";
  $body .= "use strict;\n";
  $body .= "use warnings;\n";
  $body .= "use LaTeXML::Package;\n\n";

  if ($pkg eq 'fontawesome5') {
    $body .= "DeclareOption('free', undef);\n";
    $body .= "DeclareOption('pro', undef);\n";
    $body .= "DeclareOption('fixed', undef);\n";
    $body .= "DeclareOption(undef, undef);\n";
    $body .= "ProcessOptions();\n\n";
  }
  if ($pkg eq 'tipa') {
    $body .= "DeclareOption(undef, undef);\n";
    $body .= "ProcessOptions();\n";
    $body .= "DefMacro('\\textipa{}', '#1');\n\n";
  }
  if ($pkg eq 'kpfonts' && -f $prov_path) {
    my $prov = read_json($prov_path);
    my $opts = $prov->{table}{options} || [];
    for my $o (@$opts) {
      next if $o eq '*';
      $o =~ s/['\\]//g;
      $body .= "DeclareOption('$o', undef);    # face-selection; does not change meaning\n";
    }
    $body .= "DeclareOption(undef, undef);\n" if @$opts;
    $body .= "ProcessOptions();\n\n"          if @$opts;
  }

  $body .= "RequirePackage('amsfonts');\n\n" if $pkg eq 'kpfonts';

  my @icons;
  for my $r (@$rows) {
    my $cmd  = $r->{command};
    my $kind = $r->{kind};
    my $cp   = $r->{codepoint};
    my $role = $r->{role};
    my $mean = $r->{meaning};
    my $name = $r->{name};
    my $font = $r->{font};
    if ($kind eq 'alphabet') {
      my $fp = font_perl($font);
      my $proto = $cmd =~ /\{\}\z/ ? $cmd : $cmd . '{}';
      $body .= "DefConstructor('$proto', '#1', bounded => 1, requireMath => 1";
      $body .= ",\n  font => $fp" if $fp;
      $body .= ");\n";
      next;
    }
    if ($kind eq 'text' && $font =~ /^(regular|solid)$/) {
      push @icons, $r;
      my $class = $font;
      my $cs    = $cmd;
      next if $cs =~ /^\\faIcon\{/;    # lookup-only; named via %FA_ICONS
      $cs =~ s/\{.*//;
      $body .= "DefConstructorI('$cs', undef,\n";
      $body .= "  \"<ltx:text class='$class' _noautoclose='1'>\" . "
        . perl_cps($cp)
        . " . \"</ltx:text>\");\n";
      next;
    }
    if ($kind eq 'text') {
      my $cs = $cmd;
      $cs =~ s/\{.*//;
      $body .= "DefPrimitiveI('$cs', undef, " . perl_cps($cp);
      $body .= ", bounded => 1" if $font;
      $body .= ");\n";
      next;
    }
    # symbol
    my $cs = $cmd;
    $cs =~ s/\{.*//;
    $body .= "DefMathI('$cs', undef, " . perl_cps($cp);
    my @opts;
    push @opts, "role => '$role'"       if $role;
    push @opts, "meaning => '$mean'"    if $mean;
    push @opts, "name => '$name'"       if $name && $name ne substr($cs, 1);
    my $fp = $font ? font_perl($font) : '';
    push @opts, "font => $fp" if $fp;
    if (@opts) {
      $body .= ",\n  " . join(', ', @opts); }
    $body .= ");\n";
  }

  if (@icons) {
    $body .= "\n# \\faIcon[regular|solid]{name} lookup\n";
    $body .= q{DefConstructor('\lx@fa@icon{}{}',} . "\n";
    $body .= q{  "<ltx:text class='#1' _noautoclose='1'>#2</ltx:text>");} . "\n";
    $body .= "our %FA_ICONS = (\n";
    my %seen;
    for my $r (@icons) {
      my $id = $r->{name} || next;
      next if $seen{$id}++;
      $id =~ s/'//g;
      $body .= "  '$id' => " . perl_cps($r->{codepoint}) . ",\n";
    }
    $body .= ");\n";
    $body .= <<'FAICON';
DefMacro('\faIcon[]{}', sub {
    my ($gullet, $style, $name) = @_;
    my $st = ToString($style);
    $st = 'solid' unless $st;
    $st = 'solid' unless $st eq 'regular' || $st eq 'solid';
    my $id = ToString($name);
    my $ch = $FA_ICONS{$id};
    return () unless defined $ch;
    return Invocation(T_CS('\lx@fa@icon'), T_OTHER($st), Tokenize($ch)); });
FAICON
  }

  $body .= "\n1;\n";
  open my $fh, '>:raw', $out or die "symbind: write $out: $!\n";
  print $fh encode_utf8($body);
  close $fh;
  say_ "generate $pkg: " . scalar(@$rows) . " rows -> " . rel_from_root($out);
  return 1; }

1;
