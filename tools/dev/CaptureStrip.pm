package CaptureStrip;
use strict;
use warnings;
use XML::LibXML;
use XML::LibXML::XPathContext;
use base qw(Exporter);
our @EXPORT_OK = qw(without_capture error_count);

my $LTX_NS     = 'http://dlmf.nist.gov/LaTeXML';
my $CAPTURE_NS = 'http://dlmf.nist.gov/LaTeXML/capture';

sub _libxml {
  my ($document) = @_;
  return unless $document;
  return $document if eval { $document->isa('XML::LibXML::Document') };
  return $document->getDocument if $document->can('getDocument');
  return $document; }

sub _xpath {
  my ($document) = @_;
  my $xc = XML::LibXML::XPathContext->new($document);
  $xc->registerNs(ltx     => $LTX_NS);
  $xc->registerNs(capture => $CAPTURE_NS);
  return $xc; }

# Strip the ledger, every capture:* attribute, the capture namespace
# declaration. Preserve every text node, including whitespace-only content.
# Callers comparing files must serialize compactly; formatting cannot be
# distinguished from manuscript text after it has entered the DOM.
sub without_capture {
  my ($document) = @_;
  my $dom = _libxml($document);
  return unless $dom;
  my $copy = $dom->cloneNode(1);
  my $xc   = _xpath($copy);
  foreach my $node ($xc->findnodes('/ltx:document/capture:ledger')) {
    $node->unbindNode; }
  foreach my $attr ($xc->findnodes('//@capture:*')) {
    $attr->ownerElement->removeAttributeNS($CAPTURE_NS, $attr->localname); }
  # Canonicalize the clone directly. Re-parsing a serialization here would
  # introduce parser-default dependence into the comparison itself.
  my $xml = $copy->toStringC14N(1);
  utf8::decode($xml) if defined $xml && !utf8::is_utf8($xml);
  my @remaining_capture_elements = $xc->findnodes('//*[namespace-uri()="' . $CAPTURE_NS . '"]');
  $xml =~ s/ xmlns(?::[\w.-]+)?="\Q$CAPTURE_NS\E"//g unless @remaining_capture_elements;
  return $xml; }

sub error_count {
  my ($document) = @_;
  my $dom = _libxml($document);
  return 0 unless $dom;
  my @errors = _xpath($dom)->findnodes('//ltx:ERROR');
  return 0 + @errors; }

1;
