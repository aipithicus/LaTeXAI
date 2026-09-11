#!/usr/bin/env perl
use strict;
use warnings;
use lib 'tools/dev';
use CaptureAudit qw(read_json write_json read_raw file_hash object_hash);
use CaptureStrip qw(without_capture);
use XML::LibXML;
use XML::LibXML::XPathContext;
use File::Spec;
use File::Basename qw(dirname);
use File::Path qw(make_path);
use File::Glob qw(bsd_glob);
use Cwd qw(abs_path);
use Getopt::Long qw(GetOptions);
use CaptureRuntime qw(project_searchpaths);
use Encode qw(decode FB_DEFAULT);
my ($baseline_root, $current_root, $output, $projection_pin);
GetOptions('baseline=s' => \$baseline_root, 'candidate=s' => \$current_root,
  'output=s' => \$output, 'project-baseline=s' => \$projection_pin) or die "Invalid arguments\n";
die "usage: capture-corpus-audit.pl --baseline RUN --candidate RUN --output NEW_DIR [--project-baseline RUN_SHA256]\n"
  unless $baseline_root && $current_root && $output && !@ARGV;
$baseline_root = abs_path($baseline_root) or die "Baseline missing\n";
$current_root = abs_path($current_root) or die "Candidate missing\n";
die "Output already exists\n" if -e $output;
my $proposed = File::Spec->rel2abs($output); $proposed =~ s{\\}{/}g;
for my $input ($baseline_root, $current_root) {
  die "Output must be outside input runs\n" if index(lc($proposed) . '/', lc($input) . '/') == 0;
}
my $source_pin = file_hash("$baseline_root/run.json");
die "Wrong baseline pin\n" if defined($projection_pin) && $projection_pin ne $source_pin;
my %input_hashes;
sub retained_json {
  my ($path) = @_;
  $input_hashes{$path} = file_hash($path);
  return read_json($path);
}
my @issues;
my @runs = map { retained_json("$_/run.json") } ($baseline_root, $current_root);
for my $i (0, 1) {
  my $r = $runs[$i];
  push @issues, "run-$i:incomplete" unless ($r->{schema} || '') eq 'codex-scientiae/inventory-run/0.1'
    && $r->{jobs} && $r->{receipts}{ok} == $r->{jobs}
    && !$r->{receipts}{failed} && !$r->{receipts}{missing}
    && $r->{executor}{summary}{Succeeded} == $r->{jobs} && !@{$r->{executor}{errors}};
}
make_path($output);
my $ltx = 'http://dlmf.nist.gov/LaTeXML';
my $cap = "$ltx/capture";
sub inspect {
  my ($path, $receipt, $job_directory, $stem) = @_;
  $input_hashes{$path} = file_hash($path);
  my $doc = XML::LibXML->load_xml(location => $path, keep_blanks => 1);
  my $xc = XML::LibXML::XPathContext->new($doc);
  $xc->registerNs(ltx => $ltx); $xc->registerNs(capture => $cap);
  my $base = $doc->documentElement->getAttributeNS($cap, 'base');
  my (%carriers, %classes, %groups, %raw, %source_hashes, @issues);
  my $checked = 0;
  for my $math ($xc->findnodes('//ltx:Math')) {
    my $id = $math->getAttribute('xml:id');
    push @issues, 'missing-id' unless $id;
    my %attrs = map { $_->localname => $_->getValue }
      grep { ($_->namespaceURI || '') eq $cap } $math->attributes;
    my $kind = $attrs{provenance} || '';
    $classes{$kind}++;
    my $group = $kind eq 'unlocated' ? ($attrs{unlocatedReason} || 'unlocated')
      : $kind eq 'callsite-only' ? (($attrs{callsite} || '') =~ /^\\subfloat/ ? 'subfloat'
        : ($attrs{callsite} || '') =~ /^\\tag/ ? 'tag' : 'whole-formula-callsite') : $kind;
    $groups{$group}++;
    push @issues, "duplicate-id:$id" if $carriers{$id};
    $carriers{$id} = { tex => $math->getAttribute('tex'), capture => \%attrs, group => $group,
      ancestors => [map { $_->localname } $math->findnodes('ancestor::*')] };
    if ($kind eq 'source' || $kind eq 'callsite-only') {
      my ($file_key, $start_key, $end_key, $slice_key) = $kind eq 'source'
        ? qw(file byteStart byteEnd source) : qw(callsiteFile callsiteStart callsiteEnd callsite);
      my $file = File::Spec->rel2abs($attrs{$file_key}, $base);
      $raw{$file} = read_raw($file) unless exists $raw{$file};
      $source_hashes{$file} ||= file_hash($file);
      $input_hashes{$file} ||= $source_hashes{$file};
      my ($start, $end) = @attrs{$start_key, $end_key};
      if (!defined($start) || !defined($end) || $start !~ /^\d+$/ || $end !~ /^\d+$/
        || $end < $start || $end > length($raw{$file})) { push @issues, "range:$id"; next; }
      my $bytes = substr($raw{$file}, $start, $end - $start);
      my $slice = decode('UTF-8', $bytes, FB_DEFAULT); $slice =~ s/\x{FFFD}/ /g;
      push @issues, "bytes:$id" unless $slice eq ($attrs{$slice_key} || '');
      $checked++ if $kind eq 'source';
    }
  }
  my ($ledger) = $xc->findnodes('/ltx:document/capture:ledger/capture:math');
  for my $pair ([source => 'source'], ['callsite-only' => 'callsiteOnly'],
    ['cross-source' => 'crossSource'], [unlocated => 'unlocated']) {
    push @issues, "ledger:$pair->[0]" unless ($classes{$pair->[0]} || 0) == $ledger->getAttribute($pair->[1]);
  }
  push @issues, 'ledger:total' unless scalar(keys %carriers) == $ledger->getAttribute('total');
  my $stripped = without_capture($doc);
  my @instructions = map { $_->toString } $doc->findnodes('/processing-instruction()');
  my $projection;
  if (defined $projection_pin) {
    $projection = eval { project_searchpaths($doc, $receipt, $job_directory) };
    push @issues, "runtime-projection:$@" unless $projection;
  }
  CaptureAudit::write_raw("$stem.stripped.xml", Encode::encode('UTF-8', $stripped));
  my $projected = $projection ? without_capture($projection->{document}) : $stripped;
  CaptureAudit::write_raw("$stem.projected.xml", Encode::encode('UTF-8', $projected));
  return { path => $path, xml_sha256 => file_hash($path), carriers => \%carriers,
    classes => \%classes, groups => \%groups, source_hashes => \%source_hashes,
    processing_instructions => \@instructions,
    projected_sha256 => object_hash($projected),
    runtime_projection => $projection ? { map { $_ => $projection->{$_} } qw(identity before after) } : undef,
    source_ranges_checked => $checked, stripped_sha256 => object_hash($stripped), issues => \@issues };
}
my @papers;
my @inventories;
for my $root ($baseline_root, $current_root) {
  my %inventory;
  for my $path (bsd_glob("$root/jobs/*/receipt.json")) {
    my $receipt = retained_json($path);
    my $slug = $receipt->{article}{slug};
    die "Invalid or duplicate paper identity\n" unless $slug && $slug =~ /^[\w.-]+$/ && !$inventory{$slug};
    $inventory{$slug} = { receipt => $receipt, directory => dirname($path) };
  }
  push @inventories, \%inventory;
}
push @issues, 'changed-paper-selection' unless object_hash([sort keys %{$inventories[0]}])
  eq object_hash([sort keys %{$inventories[1]}]);
for my $i (0, 1) { push @issues, "run-$i:receipt-coverage" unless keys(%{$inventories[$i]}) == $runs[$i]{jobs}; }
for my $slug (sort keys %{$inventories[0]}) {
  next unless $inventories[1]{$slug};
  my ($old_job, $job) = map { $_->{$slug}{directory} } @inventories;
  my ($old_receipt, $new_receipt) = map { $_->{$slug}{receipt} } @inventories;
  push @issues, "$slug:receipt-failed" unless ($old_receipt->{status} || '') eq 'ok' && ($new_receipt->{status} || '') eq 'ok';
  push @issues, "$slug:article-input" unless object_hash($old_receipt->{article}) eq object_hash($new_receipt->{article});
  my $before = inspect("$old_job/$slug.xml", $old_receipt, $old_job, "$output/$slug.baseline");
  my $after = inspect("$job/$slug.xml", $new_receipt, $job, "$output/$slug.candidate");
  my @counts = ({%{$old_receipt->{counts}}}, {%{$new_receipt->{counts}}});
  my @derived_counts;
  if (defined $projection_pin) {
    for my $i (0, 1) {
      my $summary = $runs[$i]{executor}{summary};
      if (!exists($counts[$i]{timedOut}) && exists($summary->{TimedOut}) && $summary->{TimedOut} == 0
          && $summary->{Succeeded} == $runs[$i]{jobs} && $summary->{Total} == $runs[$i]{jobs}) {
        $counts[$i]{timedOut} = 0;
        push @derived_counts, { side => $i ? 'candidate' : 'baseline', field => 'timedOut', value => 0,
          source => 'run.executor.summary.TimedOut', source_run_sha256 => $input_hashes{($i ? $current_root : $baseline_root) . '/run.json'} };
      }
    }
  }
  my %count_keys = map { $_ => 1 } (keys %{$counts[0]}, keys %{$counts[1]});
  my %measurements = map { $_ => 1 } qw(latexmlMs attributionMs logParseMs xmlInspectMs residualMs workerMs outputBytes);
  for my $key (sort keys %count_keys) {
    next if $measurements{$key};
    push @issues, "$slug:diagnostic-count:$key" unless
      object_hash($counts[0]{$key}) eq object_hash($counts[1]{$key});
  }
  for my $key (qw(taxonomy missingFiles undefinedMacros errorNodes internalLeaks danglingRefs)) {
    my ($old_detail, $new_detail) = ($old_receipt->{details}{$key}, $new_receipt->{details}{$key});
    if ($key eq 'undefinedMacros' || $key eq 'missingFiles') {
      $old_detail = [sort @$old_detail]; $new_detail = [sort @$new_detail]; }
    push @issues, "$slug:diagnostic-detail:$key" unless
      object_hash($old_detail) eq object_hash($new_detail);
  }
  $before->{receipt_counts} = $old_receipt->{counts};
  $after->{receipt_counts} = $new_receipt->{counts};
  my @changes;
  push @issues, "$slug:$_" for @{$before->{issues}}, @{$after->{issues}};
  push @issues, "$slug:non-capture-tree" unless $before->{projected_sha256} eq $after->{projected_sha256};
  push @issues, "$slug:runtime-invocation" if defined($projection_pin) &&
    object_hash($before->{runtime_projection}{identity}) ne object_hash($after->{runtime_projection}{identity});
  push @issues, "$slug:source-hashes" unless object_hash($before->{source_hashes}) eq object_hash($after->{source_hashes});
  push @issues, "$slug:carrier-identities" unless object_hash([sort keys %{$before->{carriers}}])
    eq object_hash([sort keys %{$after->{carriers}}]);
  for my $id (sort keys %{$before->{carriers}}) {
    my ($old, $new) = ($before->{carriers}{$id}, $after->{carriers}{$id});
    next unless $new;
    push @issues, "$slug:tex:$id" unless $old->{tex} eq $new->{tex};
    if (object_hash($old->{capture}) ne object_hash($new->{capture})) {
      push @changes, { id => $id, before => $old, after => $new };
      push @issues, "$slug:changed-capture:$id";
    }
  }
  push @issues, "$slug:classes" unless object_hash($before->{classes}) eq object_hash($after->{classes});
  push @papers, { paper => $slug, before => $before, after => $after, changes => \@changes, derived_counts => \@derived_counts,
    exact_document_equal => $before->{stripped_sha256} eq $after->{stripped_sha256} ? JSON::PP::true : JSON::PP::false,
    projected_document_equal => $before->{projected_sha256} eq $after->{projected_sha256} ? JSON::PP::true : JSON::PP::false };
}
for my $path (sort keys %input_hashes) {
  push @issues, "input-changed:$path" unless file_hash($path) eq $input_hashes{$path};
}
my $exact_differences = scalar(grep { !$_->{exact_document_equal} } @papers);
write_json("$output/comparison.json", { schema => 'latexai/corpus-comparison/1',
  baseline => $baseline_root, candidate => $current_root,
  baseline_projection => defined($projection_pin) ? { source_run_sha256 => $source_pin } : undef,
  inputs => \%input_hashes, comparator => CaptureAudit::tree_hashes(qw(tools/dev/capture-corpus-audit.pl tools/dev/CaptureRuntime.pm tools/dev/CaptureStrip.pm tools/dev/CaptureAudit.pm)),
  papers => \@papers, exact_document_differences => $exact_differences,
  issues => \@issues, qualified => @issues ? JSON::PP::false : JSON::PP::true });
for my $paper (@papers) {
  printf "%s: %d carriers, %d changed capture records, %d source ranges checked\n", $paper->{paper},
    scalar(keys %{$paper->{after}{carriers}}), scalar(@{$paper->{changes}}), $paper->{after}{source_ranges_checked};
}
print "ISSUE $_\n" for @issues;
printf "CorpusAudit compare: %d papers, %d exact document differences, %d gate issues\n", scalar(@papers), $exact_differences, scalar(@issues);
exit(@issues ? 1 : 0);
