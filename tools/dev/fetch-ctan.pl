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
#   perl tools/dev/fetch-ctan.pl --check [--receipts=DIR]
#                         regenerate the index in memory; diff against the committed ls-R
#                         and the tree; enforce the entry rule, one revision per archive,
#                         and provenance vs files. Local: no receipts required.
#                         --receipts proposes allow-list rows from missingFiles.
#   perl tools/dev/fetch-ctan.pl --from=<texlive-package> <member>...
#                         fetch named members of a TeX Live archive with no CTAN
#                         catalogue lookup (kernel files: t1enc.def, shortvrb.sty, …)
#   perl tools/dev/fetch-ctan.pl --restore
#                         re-fetch every entry under --outdir from its provenance pin

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
  from           => undef,
  restore        => 0,
  receipts       => undef,
);
GetOptions(\%opt, 'outdir=s', 'force', 'docs', 'whole-bundle', 'snapshot=s', 'mirror=s', 'quiet',
  'index', 'check', 'from=s', 'restore', 'receipts=s')
  or die usage();

sub usage {
  return "Usage: $0 [--outdir=DIR] [--force] [--docs] [--whole-bundle] [--snapshot=YYYY-MM-DD] [--mirror=URL] <package>...\n"
    . "       $0 --from=<texlive-package> <member>...\n"
    . "       $0 --restore [--outdir=DIR]\n"
    . "       $0 --index\n"
    . "       $0 --check [--receipts=DIR]\n"; }
sub say_ { print STDERR "fetch-ctan: @_\n" unless $opt{quiet}; }

my $ctan_root = File::Spec->catdir($root, 'lib-ctan');
my $package_dir = File::Spec->catdir($root, 'lib', 'LaTeXML', 'Package');

my $http = HTTP::Tiny->new(agent => 'LaTeXAI-fetch-ctan/2.0', timeout => 120);
my $json = JSON::PP->new->utf8->canonical->pretty;

my $tlnet = $opt{mirror} . '/systems/texlive/tlnet';
if ($opt{snapshot}) {
  my ($y, $m, $d) = $opt{snapshot} =~ /^(\d{4})-(\d{2})-(\d{2})$/
    or die "fetch-ctan: --snapshot must be YYYY-MM-DD\n";
  $tlnet = "https://texlive.info/tlnet-archive/$y/$m/$d/tlnet"; }

if ($opt{restore} && ($opt{check} || $opt{index} || $opt{from} || @ARGV || $opt{snapshot} || $opt{docs} || $opt{'whole-bundle'})) {
  die "fetch-ctan: --restore does not mix with --check, --index, --from, --snapshot, --docs, --whole-bundle, or package names (it uses each pin's archive URL)\n"; }
if ($opt{from} && ($opt{check} || $opt{restore} || $opt{docs} || $opt{'whole-bundle'})) {
  die "fetch-ctan: --from does not mix with --check, --restore, --docs, or --whole-bundle\n"; }
if ($opt{check} && ($opt{index} || @ARGV || $opt{from})) {
  die "fetch-ctan: --check does not take packages, --index, or --from\n"; }
if ($opt{check}) {
  exit(check_lib_ctan($ctan_root) ? 0 : 1); }
if ($opt{restore}) {
  my $ok = restore_tree($opt{outdir});
  if ($ok && lc(File::Spec->rel2abs($opt{outdir})) eq lc(File::Spec->rel2abs($ctan_root))) {
    write_index($ctan_root) or $ok = 0; }
  exit($ok ? 0 : 1); }
if ($opt{index} && !@ARGV && !$opt{from}) {
  write_index($ctan_root) or exit 1;
  exit 0; }

if ($opt{from}) {
  eval { fetch_from($opt{from}, @ARGV); 1 } or do {
    my $err = $@; chomp($err);
    print STDERR "fetch-ctan: --from=$opt{from} FAILED: $err\n";
    exit 1; };
  my $outdir_abs = File::Spec->rel2abs($opt{outdir});
  if (lc($outdir_abs) eq lc(File::Spec->rel2abs($ctan_root))) {
    write_index($ctan_root) or exit 1; }
  exit 0; }

my @packages = @ARGV or die usage();

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
  my $scratch = tempdir('latexai-ctan-XXXXXX', TMPDIR => 1, CLEANUP => 1);
  my $arc     = download_tl_archive($tl_name, undef, $scratch);
  my $archive_url = $arc->{url};
  my $sha512      = $arc->{sha512};
  my $revision    = $arc->{revision};
  my @members     = @{ $arc->{members} };

  my $is_bundle = lc($tl_name) ne lc($pkg);
  my @keep = @members;
  if ($is_bundle && !$opt{'whole-bundle'}) {
    @keep = grep { member_belongs_to($_->full_path, $pkg) } @members;
    die "bundle '$tl_name' has no member for '$pkg'; rerun with --whole-bundle to inspect" unless @keep; }

  my @runfiles;
  foreach my $m (@keep) {
    my $path = $m->full_path;
    next if $path =~ m{^tlpkg/tlpobj/.*\.tlpobj$};
    push(@runfiles, extract_runfile($target, $m)); }
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
      bytes    => $arc->{bytes},
    },
    runfiles => [ sort @runfiles ],
    styles   => [ sort @sty ],
  };
  write_raw(File::Spec->catfile($target, 'provenance.json'), $json->encode($record));
  say_("$pkg: vendored into $target");
  refresh_archive_siblings($tl_name, $arc, $pkg);
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

# runfiles may be path strings (existing pins) or {path, role} objects.
sub runfile_path {
  my ($rf) = @_;
  return $rf unless ref $rf;
  die "runfile object has no path" unless ref $rf eq 'HASH' && defined $rf->{path};
  return $rf->{path}; }

sub runfile_role {
  my ($rf) = @_;
  return 'own' unless ref $rf;
  return $rf->{role} || 'own'; }

sub runfile_record {
  my ($path, $role) = @_;
  return { path => $path, role => ($role || 'own') }; }

sub assert_safe_member_path {
  my ($path) = @_;
  die "refusing unsafe archive path '$path'"
    if $path =~ m{(^|/)\.\.(/|$)} || $path =~ m{^/} || $path =~ /^[A-Za-z]:/;
  return; }

sub extract_runfile {
  my ($target, $m) = @_;
  my $path = $m->full_path;
  assert_safe_member_path($path);
  my $dest = File::Spec->catfile($target, split(m{/}, $path));
  make_path(dirname($dest));
  write_raw($dest, $m->get_content);
  return $path; }

sub xz_or_die {
  my ($blob, $url) = @_;
  return if length($blob) >= 6 && substr($blob, 0, 6) eq "\xFD7zXZ\x00";
  # xz magic: FD 37 7A 58 5A 00. A 200 HTML challenge page (texlive.info Anubis)
  # is otherwise a successful download and a mysterious tar error later.
  die "archive is not xz (got "
    . (substr($blob, 0, 15) =~ /^<!DOCTYPE|^<html/i ? 'HTML' : sprintf('%d bytes, magic %s', length($blob), unpack('H*', substr($blob, 0, 6))))
    . ") from $url"; }

sub download_tl_archive {
  my ($tl_name, $url, $scratch) = @_;
  $tl_name =~ /^[A-Za-z0-9][A-Za-z0-9._+-]*$/ or die "'$tl_name' is not a plausible TeX Live package id";
  $url ||= "$tlnet/archive/$tl_name.tar.xz";
  $scratch ||= tempdir('latexai-ctan-XXXXXX', TMPDIR => 1, CLEANUP => 1);
  my $archive = File::Spec->catfile($scratch, "$tl_name.tar.xz");
  say_("fetching $url");
  my $dl = $http->mirror($url, $archive);
  die "download failed: $dl->{status} $dl->{reason} for $url" unless $dl->{success};
  my $blob = slurp_raw($archive);
  xz_or_die($blob, $url);
  my $sha512 = sha512_hex($blob);
  my $xz  = IO::Uncompress::UnXz->new($archive) or die "cannot open $archive as xz";
  my $tar = Archive::Tar->new($xz) or die "cannot read tar: " . (Archive::Tar->error || 'unknown');
  my @members = grep { $_->is_file } $tar->get_files;
  my $revision;
  foreach my $m (@members) {
    next unless $m->full_path =~ m{^tlpkg/tlpobj/.*\.tlpobj$};
    ($revision) = $m->get_content =~ /^revision\s+(\d+)/m;
    last if $revision; }
  return {
    name     => $tl_name,
    url      => $url,
    path     => $archive,
    blob     => $blob,
    sha512   => $sha512,
    bytes    => length($blob),
    tar      => $tar,
    members  => \@members,
    revision => $revision,
  }; }

sub member_by_path {
  my ($members) = @_;
  my %by;
  foreach my $m (@$members) {
    $by{ $m->full_path } = $m; }
  return \%by; }

# $want is a basename (t1enc.def) or a full TDS path. tlpobj is never a hit.
sub find_named_member {
  my ($want, $members) = @_;
  my @hits;
  foreach my $m (@$members) {
    my $p = $m->full_path;
    next if $p =~ m{^tlpkg/};
    if ($p eq $want || $p =~ m{(?:^|/)\Q$want\E$}) {
      push @hits, $m; } }
  die "archive has no member '$want'" unless @hits;
  if (@hits > 1) {
    die "member '$want' is ambiguous:\n  " . join("\n  ", map { $_->full_path } @hits); }
  return $hits[0]; }

# Re-pin every other entry cut from the same archive so --check's one-revision
# rule holds after a dated or live fetch.
sub refresh_archive_siblings {
  my ($tl_name, $arc, $except) = @_;
  my $by = member_by_path($arc->{members});
  foreach my $entry (ctan_entries($opt{outdir})) {
    next if defined $except && $entry eq $except;
    my $prov_path = File::Spec->catfile($opt{outdir}, $entry, 'provenance.json');
    my $prov = read_provenance($prov_path) or next;
    my $pkg = $prov->{texlive}{package} || '';
    next unless lc($pkg) eq lc($tl_name);
    my $old_sha = $prov->{texlive}{sha512} || '';
    my $old_rev = $prov->{texlive}{revision} // '';
    if ($old_sha eq $arc->{sha512} && "$old_rev" eq "$arc->{revision}") {
      say_("$entry: already pinned to $tl_name rev $old_rev");
      next; }
    say_("$entry: re-pinning to $tl_name rev $arc->{revision} (was $old_rev)");
    my $target = File::Spec->catdir($opt{outdir}, $entry);
    my @want = map { runfile_path($_) } @{ $prov->{runfiles} || [] };
    die "$entry: provenance lists no runfiles; cannot re-pin" unless @want;
    foreach my $rf (@want) {
      my $m = $by->{$rf} or die "$entry: runfile '$rf' is not in $tl_name rev $arc->{revision}";
      extract_runfile($target, $m); }
    $prov->{fetched_at} = strftime('%Y-%m-%dT%H:%M:%SZ', gmtime);
    $prov->{texlive}{revision} = $arc->{revision};
    $prov->{texlive}{sha512}   = $arc->{sha512};
    $prov->{texlive}{archive}  = $arc->{url};
    $prov->{texlive}{snapshot} = $opt{snapshot};
    $prov->{texlive}{bytes}    = $arc->{bytes};
    write_raw($prov_path, $json->encode($prov)); }
  return; }

# Kernel files with no CTAN catalogue record: members of an entry named for
# their TeX Live archive (latex, graphics). No CTAN API, no ctan.json.
sub fetch_from {
  my ($tl_name, @wants) = @_;
  $tl_name =~ /^[A-Za-z0-9][A-Za-z0-9._+-]*$/ or die "'$tl_name' is not a plausible TeX Live package id";
  die "--from=$tl_name needs at least one member (basename or TDS path)" unless @wants;
  my $target = File::Spec->catdir($opt{outdir}, $tl_name);
  if (-d $target && !$opt{force}) {
    die "$target exists; use --force to replace it"; }
  my $fetched_at = strftime('%Y-%m-%dT%H:%M:%SZ', gmtime);
  my $arc = download_tl_archive($tl_name);
  my @hits;
  my %seen;
  foreach my $want (@wants) {
    my $m = find_named_member($want, $arc->{members});
    my $path = $m->full_path;
    die "--from=$tl_name: member '$want' extracted twice as $path" if $seen{$path}++;
    push @hits, $m; }
  if (-d $target) {
    remove_tree($target); }
  make_path($target);
  my @runfiles;
  foreach my $m (@hits) {
    push(@runfiles, extract_runfile($target, $m)); }
  my @sty = grep { /\.(?:sty|cls|def|code\.tex)$/ } @runfiles;
  say_("$tl_name: " . scalar(@runfiles) . " member(s) from revision "
    . ($arc->{revision} // '?') . ": " . join(', ', @runfiles));
  my $record = {
    package    => $tl_name,
    fetched_at => $fetched_at,
    ctan       => undef,
    from       => { members => [ @wants ] },
    texlive    => {
      package  => $tl_name,
      bundle   => JSON::PP::false,
      filtered => JSON::PP::true,
      revision => $arc->{revision},
      archive  => $arc->{url},
      snapshot => $opt{snapshot},
      sha512   => $arc->{sha512},
      bytes    => $arc->{bytes},
    },
    runfiles => [ map { runfile_record($_, 'own') } sort @runfiles ],
    styles   => [ sort @sty ],
  };
  write_raw(File::Spec->catfile($target, 'provenance.json'), $json->encode($record));
  say_("$tl_name: vendored into $target");
  refresh_archive_siblings($tl_name, $arc, $tl_name);
  return; }

sub restore_entry {
  my ($outdir, $entry) = @_;
  my $dir = File::Spec->catdir($outdir, $entry);
  my $prov_path = File::Spec->catfile($dir, 'provenance.json');
  my $prov = read_provenance($prov_path)
    or die "$entry: missing or invalid provenance.json";
  my $tl = $prov->{texlive} || {};
  my $url = $tl->{archive} or die "$entry: provenance has no texlive.archive";
  my $want_sha = $tl->{sha512} or die "$entry: provenance has no texlive.sha512";
  my $tl_name = $tl->{package} || $entry;
  my @want = map { runfile_path($_) } @{ $prov->{runfiles} || [] };
  die "$entry: provenance lists no runfiles" unless @want;
  my $arc = download_tl_archive($tl_name, $url);
  if ($arc->{sha512} ne $want_sha) {
    die "$entry: archive sha512 is $arc->{sha512}, pin is $want_sha"
      . " (live archive moved; restore needs the pinned blob)"; }
  my $by = member_by_path($arc->{members});
  foreach my $rf (@want) {
    my $m = $by->{$rf} or die "$entry: pin lists '$rf' but the archive does not contain it";
    extract_runfile($dir, $m); }
  say_("$entry: restored " . scalar(@want) . " runfile(s) from $tl_name rev "
    . ($arc->{revision} // $tl->{revision} // '?'));
  return; }

sub restore_tree {
  my ($outdir) = @_;
  die "cannot restore: $outdir is not a directory" unless -d $outdir;
  my $ok = 1;
  my @entries = ctan_entries($outdir);
  die "cannot restore: $outdir has no entry directories" unless @entries;
  foreach my $entry (@entries) {
    eval { restore_entry($outdir, $entry); 1 } or do {
      my $err = $@; chomp($err);
      print STDERR "fetch-ctan: restore $entry FAILED: $err\n";
      $ok = 0; }; }
  return $ok; }

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
  my @files = map { runfile_path($_) } @$runfiles;
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
  # --from entries are named for the TeX Live archive (latex, graphics, vntex),
  # not a package to bind. Do not treat the archive name as a binding stem.
  my @stems = ($prov && $prov->{from}) ? () : ($entry);
  if ($prov && ref $prov->{styles} eq 'ARRAY') {
    foreach my $s (@{ $prov->{styles} }) {
      my $base = runfile_path($s);
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
    my $prov_e = $prov{$e};
    if ($prov_e && $prov_e->{from}) {
      my $run = (ref $prov_e->{runfiles} eq 'ARRAY') ? $prov_e->{runfiles} : [];
      if (entry_is_data($ctan_root, $e, $run)) {
        $why{$e} = 'data files (--from)'; next; } }
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
    my %listed = map { runfile_path($_) => 1 } @runfiles;
    foreach my $rf (@runfiles) {
      my $rel = runfile_path($rf);
      my $fp = File::Spec->catfile($dir, split m{/}, $rel);
      unless (-f $fp) {
        $ok = 0;
        $report->("$entry: provenance lists '$rel' but the file is absent"); } }
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
  if ($opt{receipts}) {
    propose_from_receipts($ctan_root, $opt{receipts}, $why); }
  if ($ok) {
    $report->("ok"); }
  return $ok; }

# Receipts never fail --check. They propose allow-list rows for entries the
# static scan cannot classify, and name missing stems that are not vendored.
sub propose_from_receipts {
  my ($ctan_root, $dir, $why) = @_;
  my $report = sub { print STDERR "fetch-ctan: check: @_\n"; };
  unless (-d $dir) {
    $report->("receipts: $dir is not a directory");
    return; }
  my @receipts;
  find({
    wanted => sub {
      return unless -f $_;
      push @receipts, $File::Find::name if basename($File::Find::name) eq 'receipt.json';
    },
    no_chdir => 1,
  }, $dir);
  $report->("receipts: " . scalar(@receipts) . " receipt.json under $dir");
  unless (@receipts) {
    $report->("receipts: nothing to propose");
    return; }
  my %entry_ok = map { $_ => 1 } ctan_entries($ctan_root);
  my %file_to_entry;
  foreach my $entry (keys %entry_ok) {
    my $prov = read_provenance(File::Spec->catfile($ctan_root, $entry, 'provenance.json'));
    next unless $prov && ref $prov->{runfiles} eq 'ARRAY';
    foreach my $rf (@{ $prov->{runfiles} }) {
      my $base = runfile_path($rf);
      $base =~ s{.*/}{};
      $file_to_entry{$base} = $entry; } }
  my %missing;        # file basename -> count
  my %pkg_missing;    # package name from route=missing -> count
  foreach my $path (@receipts) {
    my $raw = eval { slurp_raw($path) } or next;
    my $rec = eval { decode_json($raw) } or next;
    my $det = $rec->{details} || {};
    if (ref $det->{missingFiles} eq 'ARRAY') {
      foreach my $f (@{ $det->{missingFiles} }) {
        next unless defined $f && $f ne '';
        $f =~ s{\\}{/}g;
        $f =~ s{.*/}{};
        $missing{$f}++; } }
    if (ref $det->{packages} eq 'ARRAY') {
      foreach my $p (@{ $det->{packages} }) {
        next unless ref $p eq 'HASH';
        next unless ($p->{route} || '') eq 'missing';
        my $n = $p->{name} || next;
        $n =~ s{\\}{/}g;
        $n =~ s{.*/}{};
        $pkg_missing{$n}++; } } }
  my %allow_propose;
  my %not_vendored;
  my %seen_file;
  foreach my $file (keys %missing, keys %pkg_missing) {
    next if $seen_file{$file}++;
    my $n = ($missing{$file} || 0) + ($pkg_missing{$file} || 0);
    my $entry = $file_to_entry{$file};
    if (!$entry) {
      (my $stem = $file) =~ s/\.[^.]+$//;
      $entry = $stem if $entry_ok{$stem}; }
    if ($entry && $entry_ok{$entry}) {
      next if $why->{$entry};
      $allow_propose{$entry} += $n; }
    else {
      $not_vendored{$file} += $n; } }
  if (%allow_propose) {
    $report->("allow-list proposals (entries present but the static scan cannot classify):");
    foreach my $e (sort keys %allow_propose) {
      $report->("  $e  ($allow_propose{$e} receipt mention(s))"); } }
  else {
    $report->("allow-list proposals: none"); }
  if (%not_vendored) {
    $report->("missing stems not vendored (not allow-list rows):");
    foreach my $f (sort { $not_vendored{$b} <=> $not_vendored{$a} || $a cmp $b } keys %not_vendored) {
      $report->("  $f  ($not_vendored{$f} receipt mention(s))"); } }
  return; }
