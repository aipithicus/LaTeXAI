#!/usr/bin/env perl
# tools/dev/fetch-ctan.pl
#
# Vendor one or more LaTeX packages into lib-ctan/<pkg>/ with provenance, using
# nothing but Perl modules Strawberry ships. No TeX engine is involved.
#
#   metadata  from the CTAN catalogue    -> lib-ctan/<pkg>/ctan.json
#   runfiles  from the TeX Live archive  -> lib-ctan/<pkg>/tex/... (TDS layout; the .sty is always here)
#   docs      from the CTAN directory    -> lib-ctan/<pkg>/ctan/   (only with --docs)
#   record    of what was fetched        -> lib-ctan/<pkg>/provenance.json
#
# Why runfiles come from TeX Live and not CTAN: many packages publish only a
# .dtx/.ins pair on CTAN and the .sty is produced by running TeX over them.
# TeX Live has already done that and ships the result as one .tar.xz per
# package, which is also the artifact its package database pins by revision
# and checksum. The archive's own .tlpobj member carries the revision, so the
# 20 MB database is never needed.
#
# Bundles: a package whose CTAN record names a different TeX Live package
# (stackrel -> oberdiek) is fetched from that bundle's archive and only the
# members belonging to the requested package are kept, unless --whole-bundle.
#
# Usage:
#   perl tools/dev/fetch-ctan.pl [options] <package> [<package> ...]
#     --outdir=DIR        default: <repo>/lib-ctan
#     --force             replace an existing lib-ctan/<pkg>/
#     --docs              also fetch the CTAN directory zip (or single file) into <pkg>/ctan/
#     --whole-bundle      keep every member of a bundle archive, not just this package's
#     --snapshot=YYYY-MM-DD
#                         fetch runfiles from the dated tlnet snapshot on texlive.info
#                         instead of the live mirror (reproducible pins)
#     --mirror=URL        CTAN mirror root (default https://mirrors.ctan.org)
#     --quiet
#   perl tools/dev/fetch-ctan.pl --index
#                         write lib-ctan/ls-R from lib-ctan/*/tex/** (also runs after every
#                         fetch into lib-ctan, like mktexlsr after tlmgr)
#   perl tools/dev/fetch-ctan.pl --check
#                         regenerate the index in memory; diff against the committed ls-R
#                         and the tree; enforce the entry rule, one revision per archive,
#                         and provenance vs files. Local: no receipts.

use strict;
use warnings;
use FindBin;
use Getopt::Long;
use File::Spec;
use File::Path qw(make_path remove_tree);
use File::Temp qw(tempdir);
use File::Basename qw(basename dirname);
use File::Find;
use HTTP::Tiny;
use JSON::PP;
use Digest::SHA qw(sha512_hex);
use IO::Uncompress::UnXz;
use Archive::Tar;
use Archive::Zip qw(:ERROR_CODES);
use POSIX qw(strftime);

my $root = File::Spec->rel2abs(File::Spec->catdir($FindBin::RealBin, '..', '..'));
my %opt = (
  outdir         => File::Spec->catdir($root, 'lib-ctan'),
  force          => 0,
  docs           => 0,
  'whole-bundle' => 0,
  snapshot       => undef,
  mirror         => 'https://mirrors.ctan.org',
  quiet          => 0,
  index          => 0,
  check          => 0,
);
GetOptions(\%opt, 'outdir=s', 'force', 'docs', 'whole-bundle', 'snapshot=s', 'mirror=s', 'quiet',
  'index', 'check')
  or die usage();

sub usage {
  return "Usage: $0 [--outdir=DIR] [--force] [--docs] [--whole-bundle] [--snapshot=YYYY-MM-DD] [--mirror=URL] <package>...\n"
    . "       $0 --index\n"
    . "       $0 --check\n"; }
sub say_ { print STDERR "fetch-ctan: @_\n" unless $opt{quiet}; }

my $ctan_root = File::Spec->catdir($root, 'lib-ctan');
my $package_dir = File::Spec->catdir($root, 'lib', 'LaTeXML', 'Package');

if ($opt{check} && (@ARGV || $opt{index})) {
  die "fetch-ctan: --check does not take packages or --index\n"; }
if ($opt{check}) {
  exit(check_lib_ctan($ctan_root) ? 0 : 1); }
if ($opt{index} && !@ARGV) {
  write_index($ctan_root) or exit 1;
  exit 0; }

my @packages = @ARGV or die usage();

my $http = HTTP::Tiny->new(agent => 'LaTeXAI-fetch-ctan/2.0', timeout => 120);
my $json = JSON::PP->new->utf8->canonical->pretty;

my $tlnet = $opt{mirror} . '/systems/texlive/tlnet';
if ($opt{snapshot}) {
  my ($y, $m, $d) = $opt{snapshot} =~ /^(\d{4})-(\d{2})-(\d{2})$/
    or die "fetch-ctan: --snapshot must be YYYY-MM-DD\n";
  $tlnet = "https://texlive.info/tlnet-archive/$y/$m/$d/tlnet"; }

my $failures = 0;
foreach my $pkg (@packages) {
  eval { fetch_package($pkg); 1 } or do {
    my $err = $@; chomp($err);
    print STDERR "fetch-ctan: $pkg FAILED: $err\n";
    $failures++; }; }
my $outdir_abs = File::Spec->rel2abs($opt{outdir});
if ($failures == 0 && lc($outdir_abs) eq lc(File::Spec->rel2abs($ctan_root))) {
  write_index($ctan_root) or $failures++; }
exit($failures ? 1 : 0);

#======================================================================
sub fetch_package {
  my ($pkg) = @_;
  $pkg =~ /^[A-Za-z0-9][A-Za-z0-9._+-]*$/ or die "'$pkg' is not a plausible package id";
  my $target = File::Spec->catdir($opt{outdir}, $pkg);
  if (-d $target) {
    die "$target exists; use --force to replace it" unless $opt{force};
    remove_tree($target); }
  make_path($target);
  my $fetched_at = strftime('%Y-%m-%dT%H:%M:%SZ', gmtime);

  #--- 1. CTAN catalogue record -------------------------------------
  my $api = "https://www.ctan.org/json/2.0/pkg/$pkg";
  my $res = $http->get($api);
  die "CTAN API $res->{status} $res->{reason} for $api" unless $res->{success};
  my $meta = decode_json($res->{content});
  write_raw(File::Spec->catfile($target, 'ctan.json'), $res->{content});
  my $tl_name = $meta->{texlive} || $pkg;
  say_("$pkg: CTAN $meta->{version}{number} ($meta->{version}{date}), license $meta->{license}, texlive package '$tl_name'");

  #--- 2. TeX Live runfiles archive ---------------------------------
  my $archive_url = "$tlnet/archive/$tl_name.tar.xz";
  my $scratch     = tempdir('latexai-ctan-XXXXXX', TMPDIR => 1, CLEANUP => 1);
  my $archive     = File::Spec->catfile($scratch, "$tl_name.tar.xz");
  say_("$pkg: fetching $archive_url");
  my $dl = $http->mirror($archive_url, $archive);
  die "download failed: $dl->{status} $dl->{reason} for $archive_url" unless $dl->{success};
  my $sha512 = sha512_hex(slurp_raw($archive));

  my $xz  = IO::Uncompress::UnXz->new($archive) or die "cannot open $archive as xz";
  my $tar = Archive::Tar->new($xz) or die "cannot read tar: " . (Archive::Tar->error || 'unknown');
  my @members = grep { $_->is_file } $tar->get_files;

  my $is_bundle = lc($tl_name) ne lc($pkg);
  my @keep = @members;
  if ($is_bundle && !$opt{'whole-bundle'}) {
    @keep = grep { member_belongs_to($_->full_path, $pkg) } @members;
    die "bundle '$tl_name' has no member for '$pkg'; rerun with --whole-bundle to inspect" unless @keep; }

  my ($revision, @runfiles);
  foreach my $m (@keep) {
    my $path = $m->full_path;
    die "refusing unsafe archive path '$path'" if $path =~ m{(^|/)\.\.(/|$)} || $path =~ m{^/} || $path =~ /^[A-Za-z]:/;
    if ($path =~ m{^tlpkg/tlpobj/.*\.tlpobj$}) {
      ($revision) = $m->get_content =~ /^revision\s+(\d+)/m unless $revision;
      next; }
    my $dest = File::Spec->catfile($target, split(m{/}, $path));
    make_path(dirname($dest));
    write_raw($dest, $m->get_content);
    push(@runfiles, $path); }
  # A bundle's .tlpobj is filtered out above; read revision from the full member list.
  if (!$revision) {
    foreach my $m (@members) {
      next unless $m->full_path =~ m{^tlpkg/tlpobj/.*\.tlpobj$};
      ($revision) = $m->get_content =~ /^revision\s+(\d+)/m;
      last if $revision; } }
  my @sty = grep { /\.(?:sty|cls|def|code\.tex)$/ } @runfiles;
  die "archive for '$tl_name' yielded no runfiles for '$pkg'" unless @runfiles;
  say_("$pkg: " . scalar(@runfiles) . " runfile(s), revision " . ($revision // '?') . ", style files: " . (join(', ', @sty) || '(none)'));

  #--- 3. Optional CTAN directory zip (docs, dtx sources) -----------
  my $docs_note;
  if ($opt{docs}) {
    my $path = $meta->{ctan}{path} or die "CTAN record has no ctan.path";
    my $ctan_dir = File::Spec->catdir($target, 'ctan');
    make_path($ctan_dir);
    # The record's ctan.file flag is true even for directory packages, so it
    # cannot be trusted. A directory has a .zip rendition on the mirror; a
    # single file (a lone .dtx inside a bundle) does not. Try the zip first.
    my $zip_url = "$opt{mirror}$path.zip";
    my $zipfile = File::Spec->catfile($scratch, "$pkg.zip");
    my $r = $http->mirror($zip_url, $zipfile);
    if (!$r->{success}) {
      my $url = "$opt{mirror}$path";
      my $rf = $http->mirror($url, File::Spec->catfile($ctan_dir, basename($path)));
      die "download failed: zip $r->{status} for $zip_url; file $rf->{status} for $url" unless $rf->{success};
      $docs_note = { kind => 'single-file', url => $url }; }
    else {
      my $url = $zip_url;
      my $zip = Archive::Zip->new();
      $zip->read($zipfile) == AZ_OK or die "cannot read $zipfile";
      foreach my $member ($zip->members) {
        my $name = $member->fileName;
        die "refusing unsafe zip path '$name'" if $name =~ m{(^|/)\.\.(/|$)} || $name =~ m{^/};
        next if $member->isDirectory;
        my $dest = File::Spec->catfile($ctan_dir, split(m{/}, $name));
        make_path(dirname($dest));
        $member->extractToFileNamed($dest) == AZ_OK or die "cannot extract $name"; }
      $docs_note = { kind => 'directory-zip', url => $url }; }
    say_("$pkg: CTAN $docs_note->{kind} fetched into ctan/"); }

  #--- 4. Provenance record -----------------------------------------
  my $record = {
    package    => $pkg,
    fetched_at => $fetched_at,
    ctan       => {
      api     => $api,
      version => $meta->{version}{number},
      date    => $meta->{version}{date},
      license => $meta->{license},
      path    => $meta->{ctan}{path},
      docs    => $docs_note,
    },
    texlive => {
      package  => $tl_name,
      bundle   => ($is_bundle ? JSON::PP::true : JSON::PP::false),
      filtered => (($is_bundle && !$opt{'whole-bundle'}) ? JSON::PP::true : JSON::PP::false),
      revision => $revision,
      archive  => $archive_url,
      snapshot => $opt{snapshot},
      sha512   => $sha512,
      bytes    => -s $archive,
    },
    runfiles => [ sort @runfiles ],
    styles   => [ sort @sty ],
  };
  write_raw(File::Spec->catfile($target, 'provenance.json'), $json->encode($record));
  say_("$pkg: vendored into $target");
  return; }

# A bundle member belongs to $pkg if its basename stem is $pkg (stackrel.sty)
# or a directory component equals $pkg (tex/latex/<pkg>/...).
sub member_belongs_to {
  my ($path, $pkg) = @_;
  my @parts = split(m{/}, $path);
  my $base  = pop(@parts);
  (my $stem = $base) =~ s/\..*$//;
  return 1 if lc($stem) eq lc($pkg);
  return 1 if grep { lc($_) eq lc($pkg) } @parts;
  return 0; }

sub slurp_raw {
  my ($path) = @_;
  open(my $fh, '<:raw', $path) or die "cannot read $path: $!";
  local $/; my $c = <$fh>; close($fh); return $c; }

sub write_raw {
  my ($path, $content) = @_;
  open(my $fh, '>:raw', $path) or die "cannot write $path: $!";
  print {$fh} $content; close($fh); return; }

#======================================================================
# ls-R index and --check (lib-ctan only; reference roots are never walked)
#======================================================================
sub ctan_entries {
  my ($ctan_root) = @_;
  opendir(my $dh, $ctan_root) or die "cannot read $ctan_root: $!";
  my @entries = sort grep {
    $_ ne '.' && $_ ne '..' && -d File::Spec->catdir($ctan_root, $_)
  } readdir $dh;
  closedir $dh;
  return @entries; }

# Walk lib-ctan/*/tex/**. Returns (dir_rel => [filenames], basename => [rel paths]).
sub collect_tex_index {
  my ($ctan_root) = @_;
  my %dirs;
  my %by_name;
  foreach my $entry (ctan_entries($ctan_root)) {
    my $tex = File::Spec->catdir($ctan_root, $entry, 'tex');
    next unless -d $tex;
    find({
      wanted => sub {
        return unless -f $_;
        my $rel = File::Spec->abs2rel($File::Find::name, $ctan_root);
        $rel =~ s{\\}{/}g;
        my ($dir, $file) = $rel =~ m{^(.+)/([^/]+)$} or return;
        push @{ $dirs{$dir} }, $file;
        push @{ $by_name{$file} }, $rel;
      },
      no_chdir => 1,
    }, $tex); }
  foreach my $dir (keys %dirs) {
    $dirs{$dir} = [ sort @{ $dirs{$dir} } ]; }
  return (\%dirs, \%by_name); }

sub format_ls_R {
  my ($dirs) = @_;
  my $out = "% ls-R -- filename database for LaTeXAI's lib-ctan; written by lctan, do not edit.\n";
  $out .= "./:\nls-R\n";
  foreach my $dir (sort keys %$dirs) {
    $out .= "\n./$dir:\n";
    $out .= "$_\n" for @{ $dirs->{$dir} }; }
  return $out; }

sub duplicate_names {
  my ($by_name) = @_;
  my @dups = grep { @{ $by_name->{$_} } > 1 } sort keys %$by_name;
  return @dups; }

sub write_index {
  my ($ctan_root) = @_;
  my ($dirs, $by_name) = collect_tex_index($ctan_root);
  my @dups = duplicate_names($by_name);
  if (@dups) {
    print STDERR "fetch-ctan: duplicate bare file names (refusing to write ls-R):\n";
    foreach my $n (@dups) {
      print STDERR "  $n\n";
      print STDERR "    $_\n" for @{ $by_name->{$n} }; }
    return 0; }
  my $lsr = File::Spec->catfile($ctan_root, 'ls-R');
  write_raw($lsr, format_ls_R($dirs));
  say_("wrote $lsr");
  return 1; }

# Binding state of a CTAN-id, same rules as demand-join.pl.
sub binding_state {
  my ($pkg) = @_;
  my ($file) = grep { -f $_ } map { File::Spec->catfile($package_dir, "$pkg.$_.ltxml") } qw(sty cls tex def ldf cfg);
  return 'missing' unless $file;
  open(my $fh, '<:raw', $file) or return 'missing';
  my @lines = <$fh>;
  close $fh;
  my $live_input = 0;
  foreach my $l (@lines) {
    next if $l =~ /^\s*(#|$)/;
    $live_input++ if $l =~ /^[^#]*InputDefinitions\(/; }
  return 'native' unless $live_input;
  my $other = grep { !/^\s*(package|use|1;|InputDefinitions|\}|\)|DeclareOption|ProcessOptions|RequirePackage)/ }
    grep { !/^\s*(#|$)/ } @lines;
  return ($other <= 1) ? 'passthrough' : 'hybrid'; }

sub live_binding_requests {
  my %need;
  opendir(my $dh, $package_dir) or return \%need;
  foreach my $fn (readdir $dh) {
    next unless $fn =~ /\.ltxml$/;
    open(my $fh, '<:raw', File::Spec->catfile($package_dir, $fn)) or next;
    while (my $l = <$fh>) {
      next if $l =~ /^\s*#/;
      if ($l =~ /\bInputDefinitions\(\s*['"]([^'"]+)/) {
        $need{$1} = "InputDefinitions in $fn"; }
      if ($l =~ /\bRequirePackage\(\s*['"]([^'"]+)/) {
        $need{$1} = "RequirePackage in $fn"; } }
    close $fh; }
  closedir $dh;
  return \%need; }

sub raw_package_requires {
  my ($ctan_root, $entry) = @_;
  my $tex = File::Spec->catdir($ctan_root, $entry, 'tex');
  return () unless -d $tex;
  my %need;
  find({
    wanted => sub {
      return unless -f $_ && /\.(?:sty|cls|tex|def|ldf|cfg)$/i;
      open(my $fh, '<:raw', $_) or return;
      local $/;
      my $c = <$fh>;
      close $fh;
      return unless defined $c;
      while ($c =~ /\\(?:RequirePackage|usepackage)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}/g) {
        foreach my $n (split /\s*,\s*/, $1) {
          $n =~ s/^\s+|\s+$//g;
          $n =~ s/\s.*$//;    # drop a trailing date/version if present inside the group
          $need{$n} = 1 if $n =~ /^[A-Za-z][A-Za-z0-9_.+-]*$/; } }
    },
    no_chdir => 1,
  }, $tex);
  return keys %need; }

sub read_allow_list {
  my ($path) = @_;
  my %allow;
  return \%allow unless -f $path;
  open(my $fh, '<:raw', $path) or return \%allow;
  while (my $l = <$fh>) {
    $l =~ s/\r?\n\z//;
    $l =~ s/^\s+|\s+$//g;
    next if $l eq '' || $l =~ /^#/;
    $allow{$l} = 1; }
  close $fh;
  return \%allow; }

sub read_provenance {
  my ($path) = @_;
  return unless -f $path;
  my $raw = slurp_raw($path);
  my $rec = eval { decode_json($raw) };
  return $rec; }

# Data files the pool consumes raw: encodings, named colors, language defs, config, fd.
sub entry_is_data {
  my ($ctan_root, $entry, $runfiles) = @_;
  my @files = @$runfiles;
  return 0 unless @files;
  my $data = 0;
  foreach my $f (@files) {
    my $base = $f;
    $base =~ s{.*/}{};
    if ($base =~ /\.(?:def|ldf|cfg|fd|enc|clo)$/i) { $data++; }
    elsif ($base =~ /\.(?:sty|cls)$/i) { return 0; } }
  return $data > 0; }

# An entry may be named for a TeX Live bundle (algorithms) while its bindings
# are the member stems (algorithm, algorithmic). Prefer those.
sub entry_binding_state {
  my ($ctan_root, $entry, $prov) = @_;
  my @stems = ($entry);
  if ($prov && ref $prov->{styles} eq 'ARRAY') {
    foreach my $s (@{ $prov->{styles} }) {
      my $base = $s;
      $base =~ s{.*/}{};
      $base =~ s/\.[^.]+$//;
      push @stems, $base if $base ne ''; } }
  foreach my $stem (@stems) {
    my $st = binding_state($stem);
    return $st if $st ne 'missing'; }
  return 'missing'; }

sub justify_entries {
  my ($ctan_root) = @_;
  my $allow = read_allow_list(File::Spec->catfile($ctan_root, 'entries.txt'));
  my $requested = live_binding_requests();
  my @entries = ctan_entries($ctan_root);
  my %prov = map {
    $_ => read_provenance(File::Spec->catfile($ctan_root, $_, 'provenance.json'))
  } @entries;
  my %state = map { $_ => entry_binding_state($ctan_root, $_, $prov{$_}) } @entries;
  my %why;
  foreach my $e (@entries) {
    my $st = $state{$e};
    if ($allow->{$e}) { $why{$e} = 'allow-list'; next; }
    if ($st eq 'native') { $why{$e} = 'native census source'; next; }
    if ($st eq 'passthrough' || $st eq 'hybrid') {
      $why{$e} = "$st (binding delegates)"; next; }
    if ($requested->{$e}) { $why{$e} = "requested: $requested->{$e}"; next; } }
  # Recurse: raw files of executing entries (passthrough/hybrid/raw-only already justified).
  my $changed = 1;
  while ($changed) {
    $changed = 0;
    foreach my $e (@entries) {
      next unless $why{$e};
      next unless $state{$e} eq 'passthrough' || $state{$e} eq 'hybrid' || $state{$e} eq 'missing';
      foreach my $dep (raw_package_requires($ctan_root, $e)) {
        next if $why{$dep};
        next unless grep { $_ eq $dep } @entries;
        $why{$dep} = "required by raw $e";
        $changed = 1; } } }
  foreach my $e (@entries) {
    next if $why{$e};
    my $prov = read_provenance(File::Spec->catfile($ctan_root, $e, 'provenance.json'));
    my $run = ($prov && ref $prov->{runfiles} eq 'ARRAY') ? $prov->{runfiles} : [];
    if (entry_is_data($ctan_root, $e, $run)) {
      $why{$e} = 'data files'; } }
  return (\%why, \%state); }

sub check_lib_ctan {
  my ($ctan_root) = @_;
  my $ok = 1;
  my $report = sub { print STDERR "fetch-ctan: check: @_\n"; };
  unless (-d $ctan_root) {
    $report->("no $ctan_root");
    return 0; }
  my ($dirs, $by_name) = collect_tex_index($ctan_root);
  my @dups = duplicate_names($by_name);
  if (@dups) {
    $ok = 0;
    $report->("duplicate bare file names:");
    foreach my $n (@dups) {
      $report->("  $n");
      $report->("    $_") for @{ $by_name->{$n} }; } }
  my $expected = format_ls_R($dirs);
  my $lsr_path = File::Spec->catfile($ctan_root, 'ls-R');
  if (!-f $lsr_path) {
    $ok = 0;
    $report->("ls-R is missing; run lctan --index"); }
  else {
    my $got = slurp_raw($lsr_path);
    if ($got ne $expected) {
      $ok = 0;
      $report->("ls-R differs from the tree; run lctan --index"); } }
  my %rev_for;
  my ($why, $state) = justify_entries($ctan_root);
  foreach my $entry (ctan_entries($ctan_root)) {
    my $dir = File::Spec->catdir($ctan_root, $entry);
    my $prov_path = File::Spec->catfile($dir, 'provenance.json');
    my $prov = read_provenance($prov_path);
    if (!$prov) {
      $ok = 0;
      $report->("$entry: missing or invalid provenance.json");
      next; }
    my $sha = $prov->{texlive}{sha512} || '';
    if ($sha !~ /^[0-9a-f]{128}$/) {
      $ok = 0;
      $report->("$entry: provenance texlive.sha512 is missing or not SHA-512"); }
    my $tl = $prov->{texlive}{package} || '';
    my $rev = $prov->{texlive}{revision};
    if ($tl ne '' && defined $rev) {
      if (exists $rev_for{$tl} && $rev_for{$tl}{rev} ne $rev) {
        $ok = 0;
        $report->("archive '$tl' revision mismatch: $rev_for{$tl}{entry}=$rev_for{$tl}{rev} vs $entry=$rev"); }
      else {
        $rev_for{$tl} = { entry => $entry, rev => $rev }; } }
    my @runfiles = ref $prov->{runfiles} eq 'ARRAY' ? @{ $prov->{runfiles} } : ();
    my %listed = map { $_ => 1 } @runfiles;
    foreach my $rf (@runfiles) {
      my $fp = File::Spec->catfile($dir, split m{/}, $rf);
      unless (-f $fp) {
        $ok = 0;
        $report->("$entry: provenance lists '$rf' but the file is absent"); } }
    my $tex = File::Spec->catdir($dir, 'tex');
    if (-d $tex) {
      find({
        wanted => sub {
          return unless -f $_;
          my $rel = File::Spec->abs2rel($File::Find::name, $dir);
          $rel =~ s{\\}{/}g;
          return unless $rel =~ m{^tex/};
          unless ($listed{$rel}) {
            $ok = 0;
            $report->("$entry: file on disk not in provenance: $rel"); }
        },
        no_chdir => 1,
      }, $tex); }
    unless ($why->{$entry}) {
      $ok = 0;
      $report->("$entry: fails the entry rule (not data, not requested, not a native source, not on the allow-list); park it"); }
    else {
      say_("$entry: $why->{$entry} (binding $state->{$entry})"); } }
  if ($ok) {
    $report->("ok"); }
  return $ok; }
