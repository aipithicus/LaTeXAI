package CaptureOffAudit;
use strict;
use warnings;
use Cwd qw(abs_path);
use File::Basename qw(basename dirname);
use File::Path qw(make_path);
use File::Spec;
use Encode qw(encode);
use Digest::SHA qw(sha256_hex);
use LaTeXML::Util::Test ();
use CaptureAudit qw(json_bytes read_json write_json write_raw read_raw file_hash
  object_hash run_conversion compare_case tree_hashes verify_artifacts);
use CaptureStrip qw(without_capture error_count);

# Only load in primary prove processes, through capture-audit.pl --exec.
my $root = $ENV{LATEXAI_AUDIT_OUTPUT}
  or die "Use tools/dev/capture-audit.pl record|compare --output DIR\n";
my $baseline_root = $ENV{LATEXAI_AUDIT_BASELINE};
my $legacy_root = $ENV{LATEXAI_AUDIT_LEGACY_OFF};
my $driver = basename($0);
my $directory = File::Spec->catdir($root, $driver);
die "Driver output already exists: $directory\n" if -e $directory;
make_path($directory);
my $baseline = $baseline_root && -f "$baseline_root/$driver/report.json"
  ? read_json("$baseline_root/$driver/report.json") : undef;
my $report = { format => $CaptureAudit::FORMAT, driver => $driver, cases => {},
  inventory => {}, suites => [], skips => [], issues => [], complete => JSON::PP::false };
my %seen_names;
my %seen_legacy;
my %ordinals;
if ($baseline) {
  push @{ $report->{issues} }, @{ verify_artifacts("$baseline_root/$driver", $baseline) };
}

sub observe {
  my ($event, %data) = @_;
  if ($event eq 'suite') {
    push @{ $report->{suites} }, $data{directory};
    for my $tex (glob("$data{directory}/*.tex")) {
      (my $name = $tex) =~ s/\.tex$//;
      $report->{inventory}{$name} = { source => abs_path($tex),
        source_sha256 => file_hash($tex), golden => -f "$name.xml" ? file_hash("$name.xml") : undef };
    }
    return;
  }
  if ($event eq 'skip' || $event eq 'skip_suite') {
    push @{ $report->{skips} }, { event => $event, %data };
    $seen_names{$data{name}} = 1 if $data{name};
    if ($event eq 'skip_suite') {
      $seen_names{$_} = 1 for grep { index($_, "$data{directory}/") == 0 } keys %{ $report->{inventory} };
    }
    return;
  }
  return unless $event eq 'conversion';
  my $options = $data{options};
  my $core_options = JSON::PP->new->utf8->decode(json_bytes($data{core_options}));
  my $source = abs_path($options->{texpath}) || $options->{texpath};
  my $name = $options->{name};
  $seen_names{$name} = 1;
  my $identity = { source => $source, name => $name };
  my $ordinal = ++$ordinals{object_hash($identity)};
  my $key = object_hash({ %$identity, ordinal => $ordinal });
  my $stem = "$directory/$key";
  my $case = $report->{cases}{$key} = { %$identity, ordinal => $ordinal,
    options => $core_options, source_sha256 => -f $source ? file_hash($source) : object_hash($source),
    support_sha256 => object_hash(tree_hashes(dirname($source), @{ $core_options->{searchpaths} || [] })),
  };
  if ($core_options->{capture}) { $case->{excluded} = 'driver-already-captures'; return; }
  if ($data{failure}) {
    $case->{failure} = 'capture-off-conversion';
    $case->{diagnostic} = $data{failure};
    push @{ $report->{issues} }, "$key:capture-off-conversion";
    return;
  }
  my $doc = $data{document};
  my $off_raw = encode('UTF-8', $doc->toString(1));
  my $off_stripped = without_capture($doc);
  write_raw("$stem.driver-off.xml", $off_raw);
  write_raw("$stem.driver-off.stripped.xml", encode('UTF-8', $off_stripped));
  $case->{off_raw_sha256} = sha256_hex($off_raw);
  $case->{driver_diagnostics} = { error_nodes => error_count($doc),
    status_code => $data{status_code}, status_message => $data{status_message} };
  if ($legacy_root) {
    # This is the old key exactly: preserve the old files and compare raw bytes.
    my $legacy_key = object_hash({ source => $source, name => $name, options => $core_options });
    $seen_legacy{$legacy_key} = 1;
    my $path = "$legacy_root/$driver/$legacy_key.xml";
    $case->{legacy_off} = !-f $path ? 'new-fixture' : read_raw($path) eq $off_raw ? 'unchanged' : 'changed';
    push @{ $report->{issues} }, "$key:legacy-capture-off-$case->{legacy_off}"
      unless $case->{legacy_off} eq 'unchanged';
  }
  # Util::Test reuses a process across fixtures. Its raw bytes remain the
  # independent gate, but a fresh off control removes process history from
  # the capture-only comparison (notably repeated-pool warning counts).
  my $control = run_conversion({ texpath => $options->{texpath}, options => { %$core_options, capture => 0 } }, "$stem.off");
  if ($control->{failure}) {
    $case->{failure} = 'fresh-off-' . $control->{failure};
    $case->{diagnostic} = $control;
    push @{ $report->{issues} }, "$key:$case->{failure}";
    return;
  }
  my $on = run_conversion({ texpath => $options->{texpath}, options => { %$core_options, capture => 1 } }, "$stem.on");
  if ($on->{failure}) {
    $case->{failure} = $on->{failure};
    $case->{diagnostic} = $on;
    push @{ $report->{issues} }, "$key:$on->{failure}";
    return;
  }
  write_raw("$stem.on.xml", encode('UTF-8', $on->{raw}));
  write_raw("$stem.on.stripped.xml", encode('UTF-8', $on->{stripped}));
  write_raw("$stem.off.xml", encode('UTF-8', $control->{raw}));
  write_raw("$stem.off.stripped.xml", encode('UTF-8', $control->{stripped}));
  $case->{fresh_off_raw_sha256} = file_hash("$stem.off.xml");
  $case->{on_raw_sha256} = file_hash("$stem.on.xml");
  $case->{residual} = {
    off => { stripped_sha256 => sha256_hex(encode('UTF-8', $control->{stripped})),
      error_nodes => $control->{error_nodes}, status_code => $control->{status_code}, status_message => $control->{status_message} },
    on => { stripped_sha256 => sha256_hex(encode('UTF-8', $on->{stripped})),
      error_nodes => $on->{error_nodes}, status_code => $on->{status_code}, status_message => $on->{status_message} },
  };
  $case->{driver_context_different} = object_hash({ %{$case->{driver_diagnostics}},
      stripped_sha256 => sha256_hex(encode('UTF-8', $off_stripped)) }) ne object_hash($case->{residual}{off})
    ? JSON::PP::true : JSON::PP::false;
  $case->{different} = object_hash($case->{residual}{off}) ne object_hash($case->{residual}{on})
    ? JSON::PP::true : JSON::PP::false;
  $case->{tree_different} = $case->{residual}{off}{stripped_sha256} ne $case->{residual}{on}{stripped_sha256}
    ? JSON::PP::true : JSON::PP::false;
  $case->{diagnostics_different} = object_hash({ map { $_ => $case->{residual}{off}{$_} }
      qw(error_nodes status_code status_message) }) ne object_hash({ map { $_ => $case->{residual}{on}{$_} }
      qw(error_nodes status_code status_message) }) ? JSON::PP::true : JSON::PP::false;
  return;
}
$LaTeXML::Util::Test::CAPTURE_AUDIT_OBSERVER = sub {
  my @event = @_;
  eval { observe(@event); 1 } or do {
    my $error = $@ || 'Unknown audit observer error';
    push @{ $report->{issues} }, "observer:$error";
    warn "CaptureAudit observer: $error";
  };
};

END {
  my $original_status = $?;
  if ($report) {
    if ($baseline_root) {
      for my $key (sort keys %{ $report->{cases} }) {
        push @{ $report->{issues} }, map { "$key:$_" }
          @{ compare_case($baseline ? $baseline->{cases}{$key} : undef, $report->{cases}{$key}) };
      }
    }
    for my $name (sort keys %{ $report->{inventory} }) {
      push @{ $report->{issues} }, "unaccounted-fixture:$name" unless $seen_names{$name};
    }
    if ($baseline) {
      for my $key (sort keys %{ $baseline->{cases} }) {
        push @{ $report->{issues} }, "omitted-fixture:$key" unless exists $report->{cases}{$key};
      }
      push @{ $report->{issues} }, 'changed-skip-inventory'
        unless object_hash($baseline->{skips}) eq object_hash($report->{skips});
      push @{ $report->{issues} }, 'changed-fixture-inventory'
        unless object_hash($baseline->{inventory}) eq object_hash($report->{inventory});
    }
    if ($legacy_root) {
      for my $path (glob("$legacy_root/$driver/*.xml")) {
        my $key = basename($path, '.xml');
        push @{ $report->{issues} }, "omitted-legacy-fixture:$key" unless $seen_legacy{$key};
      }
    }
    $report->{complete} = JSON::PP::true;
    $report->{artifacts} = { map { basename($_) => file_hash($_) } grep { -f $_ } glob("$directory/*") };
    write_json("$directory/report.json", $report);
    my $n = scalar(keys %{ $report->{cases} });
    my $d = scalar(grep { $_->{different} } values %{ $report->{cases} });
    warn "CaptureAudit: $driver $n conversions, $d residuals, "
      . scalar(@{ $report->{issues} }) . " gate issues\n";
    $? = $original_status || (@{ $report->{issues} } ? 1 : 0);
  }
}
1;
