# /=====================================================================\ #
# |  LaTeXML::Core::SourceRegistry                                     | #
# | Capture-only custody of source bytes and token coordinates          | #
# |=====================================================================| #
# | Part of LaTeXML:                                                    | #
# |  Public domain software, produced as part of work done by the       | #
# |  United States Government & not subject to copyright in the US.     | #
# \=========================================================ooo==U==ooo=/ #

package LaTeXML::Core::SourceRegistry;
use strict;
use warnings;
use LaTeXML::Core::Mouth ();
use File::Basename qw(dirname);
use File::Spec;
use LaTeXML::Util::Pathname;
use base qw(LaTeXML::Common::Object);

# Source identity is deliberately independent of path text.  A fresh registry
# is installed for each conversion, and every Mouth registration gets a fresh
# opaque id even when the same path is opened more than once.
sub new {
  my ($class, %options) = @_;
  my $self = bless {
    serial           => 0,
    frame_serial     => 0,
    entries          => {},
    source_names     => {},
    order            => [],
    encoding_events  => [],
    package_requests => [],
    diagnostics      => [],
    root_request     => $options{root_request},
    root_kind        => $options{root_kind},
  }, $class;
  if (($options{root_kind} || '') eq 'file' && defined $options{root_request}) {
    my $absolute = pathname_absolute(pathname_canonical($options{root_request}));
    $$self{root_request} = $absolute;
    $$self{base} = pathname_absolute(pathname_canonical(dirname($absolute))); }
  return $self; }

sub registerSource {
  my ($self, %options) = @_;
  my $id = sprintf('source-%06d', ++$$self{serial});
  my $kind = $options{kind} || 'virtual';
  my $display = defined $options{display} ? $options{display} : '';
  $display = pathname_absolute(pathname_canonical($display))
    if $kind eq 'file' && length($display);
  my $entry = {
    id       => $id,
    kind     => $kind,
    display  => $display,
    encoding => (exists $options{encoding} ? $options{encoding} : 'UTF-8'),
    substitute => (exists $options{substitute} ? $options{substitute} : 1),
    raw      => '',
    lines    => [],
  };
  $$self{entries}{$id} = $entry;
  push(@{ $$self{order} }, $id);
  if (!$$self{root_id} && defined $$self{root_request}) {
    if (($kind eq 'literal' && ($$self{root_kind} || '') eq 'literal')
      || ($kind eq 'file' && ($$self{root_kind} || '') eq 'file'
        && lc($display) eq lc($$self{root_request}))) {
      $$self{root_id} = $id; } }
  if (defined $options{raw}) {
    $self->appendRaw($id, $options{raw}, complete => 1); }
  return $id; }

sub appendRaw {
  my ($self, $id, $chunk, %options) = @_;
  my $entry = $$self{entries}{$id};
  return () unless $entry;
  $chunk = '' unless defined $chunk;
  my $chunk_start = length($$entry{raw});
  $$entry{raw} .= $chunk;

  my @records = ();
  my $cursor = 0;
  while ($chunk =~ /(.*?)(\r\n|\r|\n)/sg) {
    my ($content, $terminator) = ($1, $2);
    my $match_end = pos($chunk);
    my $record_start = $chunk_start + $cursor;
    my $content_end  = $record_start + length($content);
    my $record_end   = $chunk_start + $match_end;
    push(@records, $self->_makeLineRecord($entry, $content, $terminator,
        $record_start, $content_end, $record_end, $options{defer_decode}));
    $cursor = $match_end; }
  my $remainder = substr($chunk, $cursor);
  if (length($remainder)) {
    my $record_start = $chunk_start + $cursor;
    my $record_end   = $record_start + length($remainder);
    push(@records, $self->_makeLineRecord($entry, $remainder, '',
        $record_start, $record_end, $record_end, $options{defer_decode})); }
  push(@{ $$entry{lines} }, @records);
  return @records; }

sub _makeLineRecord {
  my ($self, $entry, $raw, $terminator, $raw_start, $content_end, $raw_end, $defer) = @_;
  my $record = {
    rawStart => $raw_start, rawContentEnd => $content_end,
    rawEnd => $raw_end, terminator => $terminator,
  };
  $self->decodeLine($$entry{id}, $record, $$entry{encoding}) unless $defer;
  return $record; }

# File input can change encoding between logical lines, even within a single
# CR-delimited read. Record bytes when read, but decode only when consumed.
sub decodeLine {
  my ($self, $id, $record, $encoding) = @_;
  my $entry = $$self{entries}{$id};
  my $raw_start = $$record{rawStart};
  my $raw = substr($$entry{raw}, $raw_start, $$record{rawContentEnd} - $raw_start);
  my ($decoded, $units, $count) = $self->_decodeWithMap(
    { %$entry, encoding => $encoding }, $raw, $raw_start, 1);
  my @graphemes = ($decoded =~ /\X/g);
  my @spans;
  my $unit_index = 0;
  foreach my $grapheme (@graphemes) {
    my $count = length($grapheme);
    push(@spans, {
        byteStart => $$units[$unit_index]{byteStart},
        byteEnd => $$units[$unit_index + $count - 1]{byteEnd},
      });
    $unit_index += $count; }
  @{$record}{qw(decoded graphemes spans substitutions)} = ($decoded, \@graphemes, \@spans, $count);
  return $record; }

sub _decodeWithMap {
  my ($self, $entry, $raw, $absolute_start, $record_events) = @_;
  my ($decoded, $count, $units, $substitutions) = LaTeXML::Core::Mouth::decodeInput(
    $raw, $$entry{encoding}, map => 1, substitute => $$entry{substitute});
  foreach my $unit (@$units) {
    $$unit{byteStart} += $absolute_start;
    $$unit{byteEnd} += $absolute_start; }
  if ($record_events) {
    $self->_recordSubstitution($entry, $$_{byteStart}, $$_{byteEnd}) foreach @$substitutions; }
  return ($decoded, $units, $count); }

sub _recordSubstitution {
  my ($self, $entry, $start, $end) = @_;
  push(@{ $$self{encoding_events} }, {
      sourceId => $$entry{id}, byteStart => $start, byteEnd => $end,
      replacement => 'U+0020',
    });
  return; }

sub getEntry {
  my ($self, $id) = @_;
  return $$self{entries}{$id}; }

sub getLines {
  my ($self, $id) = @_;
  my $entry = $$self{entries}{$id};
  return $entry ? @{ $$entry{lines} } : (); }

sub getBase {
  my ($self) = @_;
  return $$self{base}; }

sub getRootId {
  my ($self) = @_;
  return $$self{root_id}; }

sub sourceName {
  my ($self, $id) = @_;
  my $entry = $$self{entries}{$id};
  return unless $entry;
  return 'literal' if $$entry{kind} eq 'literal';
  my $display = $$entry{display};
  if ($$entry{kind} eq 'file' && $$self{base} && length($display)) {
    my $base = $$self{base};
    my $cached = $$self{source_names}{$id};
    return $$cached[2] if $cached && $$cached[0] eq $display && $$cached[1] eq $base;
    my $relative = File::Spec->abs2rel(
      File::Spec->canonpath($display), File::Spec->canonpath($base));
    $relative =~ s!\\!/!g;
    # A name is reused on many elements. Keep the cache local to this registry
    # and check its inputs: getEntry exposes the descriptor. Relative inputs
    # also depend on cwd, so leave those uncommon lookups uncached. On Windows,
    # File::Spec returns 1 for a rooted path whose drive still comes from cwd.
    my $absolute = $^O eq 'MSWin32' ? 2 : 1;
    $$self{source_names}{$id} = [$display, $base, $relative]
      if File::Spec->file_name_is_absolute($display) >= $absolute
      && File::Spec->file_name_is_absolute($base) >= $absolute;
    return $relative; }
  $display =~ s!\\!/!g if defined $display;
  return $display; }

sub pathName {
  my ($self, $path) = @_;
  return unless defined $path;
  return $path if pathname_is_url($path);
  my $display = File::Spec->canonpath(pathname_absolute(pathname_canonical($path)));
  $display = File::Spec->abs2rel($display, File::Spec->canonpath($$self{base}))
    if $$self{base};
  $display =~ s!\\!/!g;
  return $display; }

sub rawSlice {
  my ($self, $id, $start, $end) = @_;
  my $entry = $$self{entries}{$id};
  return unless $entry && defined $start && defined $end;
  return if $start < 0 || $end < $start || $end > length($$entry{raw});
  return substr($$entry{raw}, $start, $end - $start); }

sub decodedSlice {
  my ($self, $id, $start, $end) = @_;
  my $entry = $$self{entries}{$id};
  my $raw = $self->rawSlice($id, $start, $end);
  return unless defined $raw;
  my ($decoded) = $self->_decodeWithMap($entry, $raw, $start, 0);
  return $decoded; }

sub nextFrameId {
  my ($self) = @_;
  return sprintf('expansion-%06d', ++$$self{frame_serial}); }

sub recordPackageRequest {
  my ($self, $record) = @_;
  push(@{ $$self{package_requests} }, $record) if $record;
  return; }

sub getPackageRequests {
  my ($self) = @_;
  return @{ $$self{package_requests} }; }

sub getEncodingEvents {
  my ($self) = @_;
  return @{ $$self{encoding_events} }; }

sub recordDiagnostic {
  my ($self, $type, %data) = @_;
  push(@{ $$self{diagnostics} }, { type => $type, %data });
  return; }

sub getDiagnostics {
  my ($self) = @_;
  return @{ $$self{diagnostics} }; }

#======================================================================
1;
