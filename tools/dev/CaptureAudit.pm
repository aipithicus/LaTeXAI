package CaptureAudit;
use strict;
use warnings;
use base qw(Exporter);
use Cwd qw(abs_path);
use Digest::SHA qw(sha256_hex);
use Encode qw(encode);
use File::Find;
use File::Spec;
use File::Basename qw(basename);
use JSON::PP;
use Config;
use MIME::Base64 qw(encode_base64);
use XML::LibXML;
use CaptureStrip qw(without_capture);
use CaptureRuntime qw(runtime_contract);
our @EXPORT_OK = qw(json_bytes read_json write_json read_raw write_raw file_hash
  object_hash run_conversion compare_case finish_run snapshot tree_hashes verify_artifacts restrip_report);
our $FORMAT = 'latexai-capture-audit/2';
our $COMPARISON = 'latexai/capture-comparison/2';

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
        return if $path =~ m{(?:^|/)scripts/local\.psd1$};
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
  # scripts/ holds tracked development machinery. scripts/local.psd1 is machine
  # configuration and is excluded below; resolved runtimes stay in environment.
  my $files = tree_hashes(qw(lib lib-ctan lib-symb t tools/dev scripts));
  my %changes;
  for my $path (split(/\0/, _git('diff', '--name-only', '-z', 'HEAD', '--')
        . _git('ls-files', '--others', '--exclude-standard', '-z'))) {
    next unless -f $path;
    $changes{$path} = encode_base64(read_raw($path), '');
  }
  require LaTeXML::Version;
  require XML::LibXML;
  my $snapshot = {
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
  };
  $snapshot->{runtime_contract} = runtime_contract($snapshot);
  return $snapshot; }

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

# Explicitly project retained canonical DOM evidence through the current strip.
# The pretty raw serialization is not a DOM round trip: it introduces whitespace.
# Never overwrite a historical report, raw output, diagnostic or strict verdict.
sub restrip_report {
  my ($directory, $report, $output) = @_;
  my @issues = @{ verify_artifacts($directory, $report) };
  die "Cannot re-strip corrupt evidence: @issues\n" if @issues;
  die "Projection output already exists: $output\n" if -e $output;
  die "Projection report differs from retained evidence\n"
    unless object_hash($report) eq object_hash(read_json("$directory/report.json"));
  # XML::LibXML 2.0210 initializes keepBlanks after creating the context;
  # no_blanks => 0 can therefore inherit an earlier parser's no_blanks => 1.
  # Use the audit's fresh-process boundary for historical DOM parsing too.
  # https://github.com/cpan-authors/XML-LibXML/issues/88
  my $status = system($^X, '-I', 'lib', '-I', 'tools/dev', '-MCaptureAudit', '-e',
    'CaptureAudit::_restrip_report(@ARGV)', $directory, $output);
  die "Baseline projection process failed: $status\n" if $status;
  my $projection = read_json("$output/projection.json");
  my $projected = JSON::PP->new->utf8->decode(json_bytes($report));
  $projected->{cases} = $projection->{cases};
  return $projected; }

sub _restrip_report {
  my ($directory, $output) = @_;
  my $report = read_json("$directory/report.json");
  my @issues = @{ verify_artifacts($directory, $report) };
  die "Cannot re-strip corrupt evidence: @issues\n" if @issues;
  die "Projection output already exists: $output\n" if -e $output;
  require File::Path;
  File::Path::make_path($output);
  my $projected = JSON::PP->new->utf8->decode(json_bytes($report));
  my %changes;
  for my $key (sort keys %{ $projected->{cases} }) {
    my $case = $projected->{cases}{$key};
    next if $case->{excluded};
    die "Cannot re-strip failed or incomplete case: $key\n"
      if $case->{failure} || !$case->{residual};
    for my $side (qw(off on)) {
      my $file = "$key.$side.stripped.xml";
      my $old_hash = $case->{residual}{$side}{stripped_sha256};
      die "Unverified retained tree: $file\n"
        unless ($report->{artifacts}{$file} || '') eq ($old_hash || '')
        && -f "$directory/$file" && file_hash("$directory/$file") eq $old_hash;
      # All parsing in this fresh process retains whitespace. Canonical
      # evidence has no external DTD to load.
      my $dom = XML::LibXML->new(no_blanks => 0, load_ext_dtd => 0,
        expand_entities => 0, no_network => 1)->load_xml(string => read_raw("$directory/$file"));
      my $xml = encode('UTF-8', without_capture($dom));
      write_raw("$output/$file", $xml);
      my $new_hash = sha256_hex($xml);
      $case->{residual}{$side}{stripped_sha256} = $new_hash;
      $changes{$key}{$side} = { before => $old_hash, after => $new_hash }
        if $old_hash ne $new_hash;
    }
    $case->{tree_different} = $case->{residual}{off}{stripped_sha256} ne $case->{residual}{on}{stripped_sha256}
      ? JSON::PP::true : JSON::PP::false;
    $case->{different} = object_hash($case->{residual}{off}) ne object_hash($case->{residual}{on})
      ? JSON::PP::true : JSON::PP::false;
  }
  # This is derived comparison evidence, not a newly qualified baseline.
  write_json("$output/projection.json", { source_report_sha256 => file_hash("$directory/report.json"),
      strip_sha256 => file_hash('tools/dev/CaptureStrip.pm'), changes => \%changes,
      cases => $projected->{cases}, artifacts => { map { basename($_) => file_hash($_) }
        glob("$output/*.xml") } });
  return $projected; }

# A per-driver END block cannot detect an entirely omitted driver.
sub finish_run {
  my ($directory, $drivers, $baseline_dir, $prove_status, $before, $after, $projection_pin) = @_;
  my @issues;
  my $baseline = $baseline_dir ? read_json("$baseline_dir/run.json") : undef;
  my $current_runtime = $before->{runtime_contract} || runtime_contract($before);
  my $baseline_runtime;
  if ($baseline) {
    push @issues, 'baseline-projection-pin-mismatch'
      if $projection_pin && file_hash("$baseline_dir/run.json") ne $projection_pin;
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
    for my $key (qw(perl root)) {
      push @issues, "changed-runtime-$key"
        unless object_hash($baseline->{before}{$key}) eq object_hash($before->{$key}); }
    my $same_contract = ($baseline->{comparison_contract} || '') eq $COMPARISON;
    push @issues, 'changed-comparison-contract' unless $same_contract || $projection_pin;
    if ($same_contract || $projection_pin) {
      $baseline_runtime = runtime_contract($baseline->{before});
      push @issues, 'changed-runtime-environment' unless
        object_hash($baseline_runtime->{identity}) eq object_hash($current_runtime->{identity});
    }
    else {
      push @issues, 'changed-runtime-environment' unless
        object_hash($baseline->{before}{environment}) eq object_hash($before->{environment});
    }
    # An explicit projection records the old runtime interpretation and canonical
    # trees under this comparison contract. Conversion still uses the same helper.
    for my $file (qw(tools/dev/CaptureAudit.pm tools/dev/CaptureOffAudit.pm
        tools/dev/capture-on-one.pl tools/dev/CaptureStrip.pm tools/dev/capture-audit.pl tools/dev/CaptureRuntime.pm)) {
      next if $projection_pin && $file ne 'tools/dev/capture-on-one.pl';
      push @issues, "changed-audit-implementation:$file"
        unless ($baseline->{before}{files}{$file} || '') eq ($before->{files}{$file} || ''); }
  }
  push @issues, 'input-state-changed-during-run' unless object_hash($before) eq object_hash($after);
  push @issues, "prove-failed:$prove_status" if $prove_status;
  my %reports;
  my %projections;
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
    if ($projection_pin) {
      my $projection_path = "$directory/$driver/baseline-projection/projection.json";
      if (!-f $projection_path) { push @issues, "missing-baseline-projection:$driver"; }
      else {
        my $projection = read_json($projection_path);
        push @issues, "$driver:projection-source-mismatch"
          unless $projection->{source_report_sha256} eq file_hash("$baseline_dir/$driver/report.json");
        push @issues, "$driver:projection-strip-mismatch"
          unless $projection->{strip_sha256} eq ($before->{files}{'tools/dev/CaptureStrip.pm'} || '');
        push @issues, map { "$driver:projection-$_" }
          @{ verify_artifacts("$directory/$driver/baseline-projection", $projection) };
        $projections{$driver} = { sha256 => file_hash($projection_path), changes => $projection->{changes} };
      }
    }
  }
  my $run = { format => $FORMAT, mode => $baseline ? 'compare' : 'record',
    comparison_contract => $COMPARISON,
    baseline => $baseline_dir, drivers => $drivers, reports => \%reports,
    before => $before, after_sha256 => object_hash($after),
    audited => $audited, different => $different, skipped => $skipped,
    tree_different => $tree_different, diagnostics_different => $diagnostics_different,
    issues => \@issues, qualified => @issues ? JSON::PP::false : JSON::PP::true };
  $run->{baseline_projection} = { source_run_sha256 => $projection_pin,
    comparison_contract => $COMPARISON, runtime => $baseline_runtime,
    original_environment => $baseline->{before}{environment},
    source_implementation => { map { $_ => $baseline->{before}{files}{$_} }
      grep { m{^tools/dev/} } keys %{ $baseline->{before}{files} } },
    projections => \%projections } if $projection_pin;
  write_json("$directory/run.json", $run);
  return $run; }

1;
