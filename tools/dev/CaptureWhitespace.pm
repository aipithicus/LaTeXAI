package CaptureWhitespace;
use strict;
use warnings;
use XML::LibXML;
use Cwd qw(abs_path);
use CaptureAudit qw(file_hash);
use base qw(Exporter);
our @EXPORT_OK = qw(load_whitespace_model normalize_formatting);

my $LTX_NS = 'http://dlmf.nist.gov/LaTeXML';
my $XML_NS = 'http://www.w3.org/XML/1998/namespace';

# The caller selects and pins the compiled model used by the engine. Loading
# it through Model reuses the serializer's #PCDATA decision, with no schema
# discovery, permissive fallback, or execution of document-supplied schemas.
sub load_whitespace_model {
  my ($path, $pin) = @_;
  die "Whitespace model requires its SHA-256 pin\n" unless defined($pin) && $pin =~ /^[a-f0-9]{64}$/;
  $path = abs_path($path) or die "Whitespace model missing\n";
  die "Whitespace model pin mismatch\n" unless file_hash($path) eq $pin;
  require LaTeXML::Common::Model;
  my $model = LaTeXML::Common::Model->new(schema_loaded => 1);
  $model->registerNamespace(ltx => $LTX_NS);
  $model->loadCompiledSchema($path);
  my %known = map { $_ => 1 } $model->getTags;
  die "Whitespace model must declare the LaTeXML document element\n"
    unless $known{'ltx:document'};
  my %implementation = map { $INC{$_} => file_hash($INC{$_}) }
    grep { m{^LaTeXML/.*\.pm$} } keys %INC;
  $implementation{$INC{'CaptureWhitespace.pm'}} = file_hash($INC{'CaptureWhitespace.pm'});
  return { model => $model, known => \%known, contract => {
      schema => 'latexai/model-whitespace/1', model_path => $path, model_sha256 => $pin,
      implementation => \%implementation,
      scope => 'XML whitespace text in declared element-only LaTeXML regions with admitted children; mixed, literal, foreign, unknown and unmodeled subtrees are opaque; xml:space is inherited',
      order => ['runtime-path-projection', 'model-whitespace', 'capture-strip', 'canonical-xml-with-comments'],
    } };
}

sub normalize_formatting {
  my ($document, $policy) = @_;
  my $copy = $document->cloneNode(1);
  my $model = $policy->{model};
  my $record = { removed_nodes => 0, removed_bytes => 0, by_element => {}, opaque => {} };
  my $walk;
  $walk = sub {
    my ($node, $preserve, $is_root) = @_;
    my $tag = 'ltx:' . $node->localname;
    my @children = $node->childNodes;
    my $opaque = ($node->namespaceURI || '') ne $LTX_NS ? 'foreign'
      : !$policy->{known}{$tag} ? 'unknown'
      : $model->canContain($tag, '#PCDATA') ? 'mixed-content'
      : scalar(grep { $_->nodeType == XML_CDATA_SECTION_NODE
          || ($_->nodeType == XML_TEXT_NODE && $_->textContent =~ /[^\x20\x09\x0a\x0d]/) } @children)
        ? 'unmodeled-text' : undef;
    if (!$opaque) {
      for my $child (grep { $_->nodeType == XML_ELEMENT_NODE } @children) {
        my $uri = $child->namespaceURI || '';
        # The same root metadata removed by CaptureStrip is outside the
        # manuscript model. Its neighbors are still judged by that model.
        next if $is_root && $uri eq "$LTX_NS/capture" && $child->localname eq 'ledger';
        my $prefix = $uri eq $LTX_NS ? 'ltx' : $model->getDocumentNamespacePrefix($uri, 0, 1);
        my $child_tag = $prefix ? "$prefix:" . $child->localname : $child->localname;
        if (($uri && !$prefix) || !$model->canContain($tag, $child_tag)) {
          $opaque = 'unmodeled-child'; last;
        }
      }
    }
    if ($opaque) { $record->{opaque}{$opaque}++; return; }
    if ($node->hasAttributeNS($XML_NS, 'space')) {
      # Unknown values are conservatively preserved too.
      $preserve = $node->getAttributeNS($XML_NS, 'space') ne 'default';
    }
    for my $child (@children) {
      if ($child->nodeType == XML_ELEMENT_NODE) { $walk->($child, $preserve, 0); }
      elsif (!$preserve && $child->nodeType == XML_TEXT_NODE
        && $child->textContent =~ /^[\x20\x09\x0a\x0d]+$/) {
        my $bytes = length($child->textContent); # XML whitespace is ASCII.
        $record->{removed_nodes}++;
        $record->{removed_bytes} += $bytes;
        $record->{by_element}{$tag}{nodes}++;
        $record->{by_element}{$tag}{bytes} += $bytes;
        $child->unbindNode;
      }
    }
  };
  $walk->($copy->documentElement, 0, 1) if $copy->documentElement;
  undef $walk; # Release the recursive closure and its DOM references.
  return { document => $copy, record => $record };
}

1;
