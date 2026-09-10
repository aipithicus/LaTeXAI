package CaptureAudit;
use strict;
use warnings;
use base qw(Exporter);
use Cwd qw(abs_path);
use Digest::SHA qw(sha256_hex);
use Encode qw(encode);
use File::Find;
use File::Spec;
use JSON::PP;
use Config;
use MIME::Base64 qw(encode_base64);
our @EXPORT_OK = qw(json_bytes read_json write_json read_raw write_raw file_hash
  object_hash run_conversion compare_case finish_run snapshot tree_hashes verify_artifacts);
our $FORMAT = 'latexai-capture-audit/1';

sub json_bytes { return JSON::PP->new->canonical->utf8->encode($_[0]); }
sub read_raw {
  open(my $fh, '<:raw', $_[0]) or die "read $_[0]: $!\n";
  local $/; my $raw = <$fh>; close($fh) or die $!;
  return $raw; }
sub write_raw {
  open(my $fh, '>:raw', $_[0]) or die "write $_[0]: $!\n";
  print {$fh} $_[1] or die $!;
  close($fh) or die $!; return; }
sub read_json { return JSON::PP->new->utf8->decode(read_raw($_[0])); }
sub write_json { write_raw($_[0], json_bytes($_[1])); return; }
sub file_hash {
  open(my $fh, '<:raw', $_[0]) or die "hash $_[0]: $!\n";
  my $hash = Digest::SHA->new(256)->addfile($fh)->hexdigest;
  close($fh); return $hash; }
sub object_hash { return sha256_hex(json_bytes($_[0])); }

sub tree_hashes {
  my (@roots) = @_;
  my %files;
  for my $root (@roots) {
    next unless -e $root;
    File::Find::find({ no_chdir => 1, wanted => sub {
        return unless -f $_;
        my $path = $File::Find::name;
        $path =~ s{\\}{/}g;
        $files{$path} = file_hash($File::Find::name);
      } }, $root); }
  return \%files; }

sub _git {
  open(my $fh, '-|', 'git', @_) or die "start git: $!\n";
  binmode($fh); local $/; my $raw = <$fh>;
  close($fh) or die "git @_ failed\n";
  return $raw; }

sub snapshot {
  my $head = _git('rev-parse', 'HEAD'); chomp($head);
  my $patch = _git('diff', '--binary', 'HEAD', '--');
  my $status = _git('status', '--porcelain=v1', '--untracked-files=all');
  my $files = tree_hashes(qw(lib lib-ctan lib-symb t tools/dev));
  my %changes;
  for my $path (split(/\0/, _git('diff', '--name-only', '-z', 'HEAD', '--')
        . _git('ls-files', '--others', '--exclude-standard', '-z'))) {
    next unless -f $path;
    $changes{$path} = encode_base64(read_raw($path), '');
  }
  require LaTeXML::Version;
  require XML::LibXML;
  return {
    format => $FORMAT, root => abs_path('.'), engine_commit => $head,
    dirty_status => $status, dirty_patch_sha256 => sha256_hex($patch),
    dirty_patch_base64 => encode_base64($patch, ''), uncommitted_files_base64 => \%changes,
    generated_revision => $LaTeXML::Version::REVISION,
    files => $files, files_sha256 => object_hash($files),
    perl => { executable => $^X, sha256 => file_hash($^X), version => "$^V",
      archname => $Config{archname}, libxml => $XML::LibXML::VERSION,
      libxml_runtime => XML::LibXML::LIBXML_RUNTIME_VERSION() },
    environment => { map { $_ => $ENV{$_} } qw(PERL_ROOT PERL5LIB PERL5OPT
      LATEXML_KPSEWHICH LATEXML_KPSEWHICH_CACHE_ONLY LATEXAI_AUDIT_JOBS CI) },
  }; }

# File-based JSON preserves nested options without shell quoting. Requests and
# results remain evidence. A process failure always wins over the helper JSON.
sub run_conversion {
  my ($request, $stem, $helper) = @_;
  $helper ||= File::Spec->catfile('tools', 'dev', 'capture-on-one.pl');
  die "Helper evidence already exists: $stem\n" if -e "$stem.request.json" || -e "$stem.result.json";
  write_json("$stem.request.json", { format => $FORMAT, %$request });
  my $status = system($^X, '-I', 'lib', '-I', 'tools/dev', $helper,
    "$stem.request.json", "$stem.result.json");
  my ($result, $decode_error);
  if (-f "$stem.result.json") {
    $result = eval { read_json("$stem.result.json") };
    $decode_error = $@; }
  return { failure => 'helper-process', process_status => $status, result => $result }
    if $status != 0;
  return { failure => 'helper-protocol', error => $decode_error || 'No result object' }
    unless ref($result) eq 'HASH' && ($result->{format} || '') eq $FORMAT;
  return { failure => 'helper-options', error => 'Helper options differ from request' }
    unless object_hash($result->{options}) eq object_hash($request->{options});
  return { failure => 'conversion', result => $result } unless $result->{ok};
  for my $key (qw(raw stripped error_nodes status_code status_message)) {
    return { failure => 'helper-protocol', error => "Missing $key" }
      unless defined $result->{$key} && !ref($result->{$key}); }
  return { failure => 'helper-protocol', error => 'Invalid engine counts/status' }
    unless $result->{error_nodes} =~ /^\d+$/ && $result->{status_code} =~ /^[0-3]$/;
  return $result; }

# Conservative: even removal needs an explanation. Raw capture-off equality is
# an independent verdict, not a consequence of the residual signature.
sub compare_case {
  my ($baseline, $current) = @_;
  my @issues;
  return ['new-fixture'] unless $baseline;
  for my $key (qw(source_sha256 options support_sha256)) {
    push @issues, "changed-$key" unless object_hash($baseline->{$key}) eq object_hash($current->{$key}); }
  push @issues, 'capture-off-bytes' if defined($current->{off_raw_sha256})
    && ($baseline->{off_raw_sha256} || '') ne $current->{off_raw_sha256};
  push @issues, 'changed-driver-diagnostics'
    unless object_hash($baseline->{driver_diagnostics}) eq object_hash($current->{driver_diagnostics});
  if ($current->{failure}) { push @issues, $current->{failure}; return \@issues; }
  if ($baseline->{excluded} || $current->{excluded}) {
    push @issues, 'changed-exclusion' unless ($baseline->{excluded} || '') eq ($current->{excluded} || '');
    return \@issues;
  }
  if (object_hash($baseline->{residual}) ne object_hash($current->{residual})) {
    push @issues, $baseline->{different}
      ? ($current->{different} ? 'changed-residual' : 'removed-residual')
      : ($current->{different} ? 'new-residual' : 'changed-pair'); }
  return \@issues; }

sub verify_artifacts {
  my ($directory, $report) = @_;
  my @issues;
  for my $file (sort keys %{ $report->{artifacts} || {} }) {
    push @issues, "artifact-integrity:$file"
      unless -f "$directory/$file" && file_hash("$directory/$file") eq $report->{artifacts}{$file};
  }
  return \@issues; }

# A per-driver END block cannot detect an entirely omitted driver.
sub finish_run {
  my ($directory, $drivers, $baseline_dir, $prove_status, $before, $after) = @_;
  my @issues;
  my $baseline = $baseline_dir ? read_json("$baseline_dir/run.json") : undef;
  if ($baseline) {
    push @issues, 'baseline-not-qualified' unless $baseline->{qualified};
    for my $driver (@{ $baseline->{drivers} }) {
      my $path = "$baseline_dir/$driver/report.json";
      if (!-f $path || file_hash($path) ne ($baseline->{reports}{$driver}{sha256} || '')) {
        push @issues, "baseline-report-integrity:$driver";
      }
      else {
        push @issues, map { "$driver:$_" } @{ verify_artifacts("$baseline_dir/$driver", read_json($path)) };
      }
    }
    push @issues, 'changed-driver-selection' unless object_hash($baseline->{drivers}) eq object_hash($drivers);
    for my $key (qw(perl environment root)) {
      push @issues, "changed-runtime-$key"
        unless object_hash($baseline->{before}{$key}) eq object_hash($before->{$key}); }
    # Engine/library changes are the subject of comparison. The comparator
    # itself must stay identical; a new normalizer needs a new explicit record.
    for my $file (qw(tools/dev/CaptureAudit.pm tools/dev/CaptureOffAudit.pm
        tools/dev/capture-on-one.pl tools/dev/CaptureStrip.pm tools/dev/capture-audit.pl)) {
      push @issues, "changed-audit-implementation:$file"
        unless ($baseline->{before}{files}{$file} || '') eq ($before->{files}{$file} || ''); }
  }
  push @issues, 'input-state-changed-during-run' unless object_hash($before) eq object_hash($after);
  push @issues, "prove-failed:$prove_status" if $prove_status;
  my %reports;
  my ($audited, $different, $skipped, $tree_different, $diagnostics_different) = (0, 0, 0, 0, 0);
  for my $driver (@$drivers) {
    my $path = "$directory/$driver/report.json";
    unless (-f $path) { push @issues, "missing-driver-report:$driver"; next; }
    my $report = eval { read_json($path) };
    unless ($report && $report->{complete}) { push @issues, "incomplete-driver:$driver"; next; }
    $reports{$driver} = { sha256 => file_hash($path),
      cases => scalar(keys %{ $report->{cases} }), skipped => scalar(@{ $report->{skips} }),
      issues => $report->{issues} };
    $audited += scalar(grep { !$_->{failure} && !$_->{excluded} } values %{ $report->{cases} });
    $different += scalar(grep { $_->{different} } values %{ $report->{cases} });
    $tree_different += scalar(grep { $_->{tree_different} } values %{ $report->{cases} });
    $diagnostics_different += scalar(grep { $_->{diagnostics_different} } values %{ $report->{cases} });
    $skipped += scalar(@{ $report->{skips} });
    push @issues, map { "$driver:$_" } @{ $report->{issues} };
  }
  my $run = { format => $FORMAT, mode => $baseline ? 'compare' : 'record',
    baseline => $baseline_dir, drivers => $drivers, reports => \%reports,
    before => $before, after_sha256 => object_hash($after),
    audited => $audited, different => $different, skipped => $skipped,
    tree_different => $tree_different, diagnostics_different => $diagnostics_different,
    issues => \@issues, qualified => @issues ? JSON::PP::false : JSON::PP::true };
  write_json("$directory/run.json", $run);
  return $run; }

1;
