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
# declaration, and whitespace-only text (pretty-print wrapping of capture
# attributes must not look like an ltx-tree change).
sub without_capture {
  my ($document) = @_;
  my $dom = _libxml($document);
  return unless $dom;
  my $copy = $dom->cloneNode(1);
  my $xc   = _xpath($copy);
  foreach my $node ($xc->findnodes('/ltx:document/capture:ledger')) {
    my $indent = $node->previousSibling;
    $indent->unbindNode if $indent && $indent->nodeType == XML_TEXT_NODE && $indent->data =~ /^\s*$/;
    $node->unbindNode; }
  foreach my $attr ($xc->findnodes('//@capture:*')) {
    $attr->ownerElement->removeAttributeNS($CAPTURE_NS, $attr->localname); }
  foreach my $text ($xc->findnodes('//text()')) {
    $text->unbindNode if $text->data =~ /^\s*$/; }
  my $xml = $copy->toString(0);
  utf8::decode($xml) if defined $xml && !utf8::is_utf8($xml);
  $xml =~ s/ xmlns:capture="\Q$CAPTURE_NS\E"//g;
  return $xml; }

sub error_count {
  my ($document) = @_;
  my $dom = _libxml($document);
  return 0 unless $dom;
  my @errors = _xpath($dom)->findnodes('//ltx:ERROR');
  return 0 + @errors; }

1;
