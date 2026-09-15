package CaptureCompare;
use strict;
use warnings;
use Exporter 'import';
use CaptureAudit qw(read_raw file_hash object_hash);
use CaptureStrip qw(without_capture);
use CaptureRuntime qw(project_searchpaths canonical_path);
use XML::LibXML;
use XML::LibXML::XPathContext;
use File::Spec;
use Encode qw(decode encode FB_DEFAULT);
use JSON::PP;
our @EXPORT_OK = qw(inspect_condition compare_paper);
my $ltx = 'http://dlmf.nist.gov/LaTeXML';
my $cap = "$ltx/capture";
sub invocation_capture {
  my ($receipt) = @_;
  return 0 + grep { $_ eq '--capture' } @{ $receipt->{details}{arguments} || [] };
}
sub identity_without_capture {
  my ($identity) = @_;
  return unless $identity;
  my @options = grep { ref($_) || $_ ne '--capture' } @{ $identity->{options} || [] };
  return { %$identity, options => \@options };
}
sub comparison_identity {
  my ($runtime, $receipt) = @_;
  my $conversion = $receipt->{conversion_identity} or return $runtime;
  my $engine = canonical_path($receipt->{engine_root});
  my $source = canonical_path($receipt->{sourceTree});
  my $perl = canonical_path($receipt->{details}{perl});
  die "Conversion roots disagree with recorded invocation\n"
    unless $runtime->{engine} eq $engine && $runtime->{source} eq $source && $runtime->{perl} eq $perl;
  my $relocate;
  $relocate = sub {
    my ($value) = @_;
    return {map {$_=>$relocate->($value->{$_})} keys %$value} if ref($value) eq 'HASH';
    return [map {$relocate->($_)} @$value] if ref($value) eq 'ARRAY';
    return $value if ref($value) || !defined($value);
    for my $root ([$engine,'engine'], [$source,'source'], [$perl,'perl']) {
      return '<'.$root->[1].'>'.substr($value,length($root->[0]))
        if $value eq $root->[0] || index($value,$root->[0].'/') == 0;
    }
    return $value;
  };
  return {%{$relocate->($runtime)}, conversion_inputs=>{
    map {$_=>$conversion->{$_}} qw(engine source entrypoint environment environmentPolicy powershell hostRuntime memoryMethod)}};
}
sub inspect_condition {
  my ($context, $path, $receipt, $job_directory, $stem, $require_ledger) = @_;
  my $whitespace = $context->{whitespace};
  $context->{inputs}{$path} = file_hash($path);
  my $doc = XML::LibXML->load_xml(location => $path, keep_blanks => 1);
  my $xc = XML::LibXML::XPathContext->new($doc);
  $xc->registerNs(ltx => $ltx); $xc->registerNs(capture => $cap);
  my $base = $doc->documentElement->getAttributeNS($cap, 'base');
  my (%carriers, %classes, %groups, %raw, %source_hashes, %math_tex, @issues);
  my $checked = 0;
  for my $math ($xc->findnodes('//ltx:Math')) {
    my $id = $math->getAttribute('xml:id');
    push @issues, 'missing-id' unless $id;
    $math_tex{$id} = $math->getAttribute('tex') // '' if $id;
    my %attrs = map { $_->localname => $_->getValue }
      grep { ($_->namespaceURI || '') eq $cap } $math->attributes;
    my $kind = $attrs{provenance} || '';
    $classes{$kind}++;
    my $group = $kind eq 'unlocated' ? ($attrs{unlocatedReason} || 'unlocated')
      : $kind eq 'callsite-only' ? (($attrs{callsite} || '') =~ /^\\subfloat/ ? 'subfloat'
        : ($attrs{callsite} || '') =~ /^\\tag/ ? 'tag' : 'whole-formula-callsite') : $kind;
    $groups{$group}++;
    push @issues, "duplicate-id:$id" if $id && $carriers{$id};
    $carriers{$id} = { tex => $math->getAttribute('tex'), capture => \%attrs, group => $group,
      ancestors => [map { $_->localname } $math->findnodes('ancestor::*')] } if $id;
    if ($kind eq 'source' || $kind eq 'callsite-only') {
      my ($file_key, $start_key, $end_key, $slice_key) = $kind eq 'source'
        ? qw(file byteStart byteEnd source) : qw(callsiteFile callsiteStart callsiteEnd callsite);
      my $file = File::Spec->rel2abs($attrs{$file_key}, $base);
      $raw{$file} = read_raw($file) unless exists $raw{$file};
      $source_hashes{$file} ||= file_hash($file);
      $context->{inputs}{$file} ||= $source_hashes{$file};
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
  if ($require_ledger) {
    if ($ledger) {
      for my $pair ([source => 'source'], ['callsite-only' => 'callsiteOnly'],
        ['cross-source' => 'crossSource'], [unlocated => 'unlocated']) {
        push @issues, "ledger:$pair->[0]" unless ($classes{$pair->[0]} || 0) == $ledger->getAttribute($pair->[1]);
      }
      push @issues, 'ledger:total' unless scalar(keys %carriers) == $ledger->getAttribute('total');
    }
    else {
      push @issues, 'missing-ledger';
    }
  }
  my $stripped = without_capture($doc);
  my @instructions = map { $_->toString } $doc->findnodes('/processing-instruction()');
  my $projection;
  if ($context->{project}) {
    $projection = eval { project_searchpaths($doc, $receipt, $job_directory) };
    push @issues, "runtime-projection:$@" unless $projection;
  }
  CaptureAudit::write_raw("$stem.stripped.xml", encode('UTF-8', $stripped));
  my $projected = $projection ? without_capture($projection->{document}) : $stripped;
  CaptureAudit::write_raw("$stem.projected.xml", encode('UTF-8', $projected));
  my ($normalization, $normalized);
  if ($whitespace) {
    $normalization = CaptureWhitespace::normalize_formatting($projection ? $projection->{document} : $doc, $whitespace);
    $normalized = without_capture($normalization->{document});
    CaptureAudit::write_raw("$stem.normalized.xml", encode('UTF-8', $normalized));
  }
  return { path => $path, xml_sha256 => file_hash($path), carriers => \%carriers,
    classes => \%classes, groups => \%groups, source_hashes => \%source_hashes,
    math_tex => \%math_tex, processing_instructions => \@instructions,
    projected_sha256 => object_hash($projected),
    comparison_sha256 => object_hash(defined($normalized) ? $normalized : $projected),
    normalization => $normalization ? $normalization->{record} : undef,
    runtime_projection => $projection ? { map { $_ => $projection->{$_} } qw(identity before after) } : undef,
    source_ranges_checked => $checked, stripped_sha256 => object_hash($stripped), issues => \@issues };
}

sub compare_paper {
  my ($context, $slug, $old_receipt, $new_receipt, $old_job, $job, $output, %options) = @_;
  my $parity = ($options{mode} || 'replay') eq 'parity';
  my @issues;
  push @issues, "$slug:receipt-failed" unless ($old_receipt->{status} || '') eq 'ok' && ($new_receipt->{status} || '') eq 'ok';
  push @issues, "$slug:article-input" unless object_hash($old_receipt->{article}) eq object_hash($new_receipt->{article});
  my $off_capture = invocation_capture($old_receipt);
  my $on_capture = invocation_capture($new_receipt);
  if ($parity) {
    push @issues, "$slug:off-has-capture" if $off_capture;
    push @issues, "$slug:on-missing-capture" unless $on_capture;
  }
  else {
    push @issues, "$slug:missing-capture" unless $off_capture && $on_capture;
  }
  my $before = inspect_condition($context, $options{old_xml} || "$old_job/$slug.xml", $old_receipt,
    $old_receipt->{conversion_job} || $old_job, "$output/$slug.baseline", $parity ? 0 : 1);
  my $after = inspect_condition($context, $options{new_xml} || "$job/$slug.xml", $new_receipt,
    $new_receipt->{conversion_job} || $job, "$output/$slug.candidate", 1);
  my @counts = @{$options{counts} || [{%{$old_receipt->{counts}}}, {%{$new_receipt->{counts}}}]};
  my @derived_counts = @{$options{derived_counts} || []};
  my %count_keys = map { $_ => 1 } (keys %{ $counts[0] }, keys %{ $counts[1] });
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
  push @issues, "$slug:$_" for @{ $before->{issues} }, @{ $after->{issues} };
  push @issues, "$slug:non-capture-tree" unless $before->{comparison_sha256} eq $after->{comparison_sha256};
  if ($context->{project} && $before->{runtime_projection} && $after->{runtime_projection}) {
    my $left = $parity ? identity_without_capture($before->{runtime_projection}{identity})
      : $before->{runtime_projection}{identity};
    my $right = $parity ? identity_without_capture($after->{runtime_projection}{identity})
      : $after->{runtime_projection}{identity};
    $left = comparison_identity($left, $old_receipt);
    $right = comparison_identity($right, $new_receipt);
    push @issues, "$slug:runtime-invocation" unless object_hash($left) eq object_hash($right);
  }
  if ($parity) {
    push @issues, "$slug:math-tex" unless object_hash($before->{math_tex}) eq object_hash($after->{math_tex});
  }
  else {
    push @issues, "$slug:source-hashes" unless object_hash($before->{source_hashes}) eq object_hash($after->{source_hashes});
    push @issues, "$slug:carrier-identities" unless object_hash([sort keys %{ $before->{carriers} }])
      eq object_hash([sort keys %{ $after->{carriers} }]);
    for my $id (sort keys %{ $before->{carriers} }) {
      my ($old, $new) = ($before->{carriers}{$id}, $after->{carriers}{$id});
      next unless $new;
      push @issues, "$slug:tex:$id" unless $old->{tex} eq $new->{tex};
      if (object_hash($old->{capture}) ne object_hash($new->{capture})) {
        push @changes, { id => $id, before => $old, after => $new };
        push @issues, "$slug:changed-capture:$id";
      }
    }
    push @issues, "$slug:classes" unless object_hash($before->{classes}) eq object_hash($after->{classes});
  }
  return { paper => $slug, before => $before, after => $after, issues => \@issues, changes => \@changes, derived_counts => \@derived_counts,
    exact_document_equal => $before->{stripped_sha256} eq $after->{stripped_sha256} ? JSON::PP::true : JSON::PP::false,
    projected_document_equal => $before->{projected_sha256} eq $after->{projected_sha256} ? JSON::PP::true : JSON::PP::false,
    comparison_document_equal => $before->{comparison_sha256} eq $after->{comparison_sha256} ? JSON::PP::true : JSON::PP::false };
}
1;
