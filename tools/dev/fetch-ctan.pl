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

use strict;
use warnings;
use FindBin;
use Getopt::Long;
use File::Spec;
use File::Path qw(make_path remove_tree);
use File::Temp qw(tempdir);
use File::Basename qw(basename dirname);
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
);
GetOptions(\%opt, 'outdir=s', 'force', 'docs', 'whole-bundle', 'snapshot=s', 'mirror=s', 'quiet')
  or die usage();
my @packages = @ARGV or die usage();

sub usage { return "Usage: $0 [--outdir=DIR] [--force] [--docs] [--whole-bundle] [--snapshot=YYYY-MM-DD] [--mirror=URL] <package>...\n"; }
sub say_ { print STDERR "fetch-ctan: @_\n" unless $opt{quiet}; }

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
