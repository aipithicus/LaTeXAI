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
use Encode qw(decode encode FB_CROAK FB_DEFAULT);
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
    encoding => $options{encoding} || 'UTF-8',
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
        $record_start, $content_end, $record_end));
    $cursor = $match_end; }
  my $remainder = substr($chunk, $cursor);
  if (length($remainder)) {
    my $record_start = $chunk_start + $cursor;
    my $record_end   = $record_start + length($remainder);
    push(@records, $self->_makeLineRecord($entry, $remainder, '',
        $record_start, $record_end, $record_end)); }
  push(@{ $$entry{lines} }, @records);
  return @records; }

sub _makeLineRecord {
  my ($self, $entry, $raw, $terminator, $raw_start, $content_end, $raw_end) = @_;
  my ($decoded, $units) = $self->_decodeWithMap($entry, $raw, $raw_start, 1);
  my @graphemes = ($decoded =~ /\X/g);
  my @spans = ();
  my $unit_index = 0;
  foreach my $grapheme (@graphemes) {
    my @characters = ($grapheme =~ /./sg);
    my $count = scalar(@characters);
    if ($count && defined $$units[$unit_index]) {
      push(@spans, {
          byteStart => $$units[$unit_index]{byteStart},
          byteEnd   => $$units[$unit_index + $count - 1]{byteEnd},
        }); }
    else {
      push(@spans, { byteStart => $raw_start, byteEnd => $raw_start }); }
    $unit_index += $count; }
  return {
    decoded       => $decoded,
    graphemes     => \@graphemes,
    spans         => \@spans,
    rawStart      => $raw_start,
    rawContentEnd => $content_end,
    rawEnd        => $raw_end,
    terminator    => $terminator,
  }; }

sub _decodeWithMap {
  my ($self, $entry, $raw, $absolute_start, $record_events) = @_;
  my $encoding = $$entry{encoding} || 'UTF-8';
  return $self->_decodeUTF8WithMap($entry, $raw, $absolute_start, $record_events)
    if $encoding =~ /^utf-?8$/i;

  my $decode_input = $raw;
  my $decoded = decode($encoding, $decode_input, FB_DEFAULT);
  my @characters = ($decoded =~ /./sg);
  my @units = ();
  my $cursor = 0;
  my $result = '';
  for (my $i = 0 ; $i < scalar(@characters) ; $i++) {
    my $character = $characters[$i];
    my ($start, $end) = ($cursor, $cursor);
    if ($character eq "\x{FFFD}") {
      $end = $cursor + 1;
      # Find the next reversible character when possible; this groups the
      # exact offending byte run consumed into this replacement.
      if ($i + 1 < scalar(@characters) && $characters[$i + 1] ne "\x{FFFD}") {
        my $next_character = $characters[$i + 1];
        my $next = eval { encode($encoding, $next_character, FB_CROAK) };
        if (defined $next) {
          my $found = index($raw, $next, $cursor + 1);
          $end = $found if $found >= 0; } }
      $end = length($raw) if $end > length($raw);
      $character = ' ';
      $self->_recordSubstitution($entry, $absolute_start + $start, $absolute_start + $end)
        if $record_events; }
    else {
      my $encode_input = $character;
      my $encoded = eval { encode($encoding, $encode_input, FB_CROAK) };
      $encoded = '' unless defined $encoded;
      $end = $cursor + length($encoded);
      $end = length($raw) if $end > length($raw); }
    push(@units, { byteStart => $absolute_start + $start, byteEnd => $absolute_start + $end });
    $cursor = $end;
    $result .= $character; }
  return ($result, \@units); }

sub _decodeUTF8WithMap {
  my ($self, $entry, $raw, $absolute_start, $record_events) = @_;
  my @units = ();
  my $decoded = '';
  my $length = length($raw);
  my $cursor = 0;
  while ($cursor < $length) {
    my $b0 = ord(substr($raw, $cursor, 1));
    my $width = 0;
    if ($b0 <= 0x7F) { $width = 1; }
    elsif ($b0 >= 0xC2 && $b0 <= 0xDF && $cursor + 1 < $length) {
      my $b1 = ord(substr($raw, $cursor + 1, 1));
      $width = 2 if $b1 >= 0x80 && $b1 <= 0xBF; }
    elsif ($b0 >= 0xE0 && $b0 <= 0xEF && $cursor + 2 < $length) {
      my $b1 = ord(substr($raw, $cursor + 1, 1));
      my $b2 = ord(substr($raw, $cursor + 2, 1));
      my $valid_b1 = ($b0 == 0xE0 ? ($b1 >= 0xA0 && $b1 <= 0xBF)
        : ($b0 == 0xED ? ($b1 >= 0x80 && $b1 <= 0x9F)
          : ($b1 >= 0x80 && $b1 <= 0xBF)));
      $width = 3 if $valid_b1 && $b2 >= 0x80 && $b2 <= 0xBF; }
    elsif ($b0 >= 0xF0 && $b0 <= 0xF4 && $cursor + 3 < $length) {
      my $b1 = ord(substr($raw, $cursor + 1, 1));
      my $b2 = ord(substr($raw, $cursor + 2, 1));
      my $b3 = ord(substr($raw, $cursor + 3, 1));
      my $valid_b1 = ($b0 == 0xF0 ? ($b1 >= 0x90 && $b1 <= 0xBF)
        : ($b0 == 0xF4 ? ($b1 >= 0x80 && $b1 <= 0x8F)
          : ($b1 >= 0x80 && $b1 <= 0xBF)));
      $width = 4 if $valid_b1
        && $b2 >= 0x80 && $b2 <= 0xBF && $b3 >= 0x80 && $b3 <= 0xBF; }

    my ($character, $end);
    if ($width) {
      $end = $cursor + $width;
      my $bytes = substr($raw, $cursor, $width);
      $character = decode('UTF-8', $bytes, FB_CROAK); }
    else {
      # Encode's UTF-8 decoder replaces each malformed leading byte.  Keeping
      # that one-byte interval is what makes the substitution event auditable.
      $end = $cursor + 1;
      $character = "\x{FFFD}"; }
    if ($character eq "\x{FFFD}") {
      $character = ' ';
      $self->_recordSubstitution($entry, $absolute_start + $cursor, $absolute_start + $end)
        if $record_events; }
    $decoded .= $character;
    push(@units, { byteStart => $absolute_start + $cursor, byteEnd => $absolute_start + $end });
    $cursor = $end; }
  return ($decoded, \@units); }

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
    $display = File::Spec->abs2rel(
      File::Spec->canonpath($display), File::Spec->canonpath($$self{base})); }
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
