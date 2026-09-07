package LaTeXAI::Post;
use strict;
use warnings;
use Time::HiRes qw(time);
use LaTeXML::Common::XML;

sub load_file {
  my ($class, $path) = @_;
  return LaTeXML::Common::XML::Parser->new->parseFile($path);
}

# Bibliography completion is intentionally outside Markdown traversal timings.
# Legacy processors work on a clone; the supplied IR remains the authority.
sub prepare {
  my ($class, $dom, %options) = @_;
  my $start = time;
  my $xp = XML::LibXML::XPathContext->new($dom);
  $xp->registerNs(ltx => 'http://dlmf.nist.gov/LaTeXML');
  my @external = $xp->findnodes('//ltx:bibliography[@files][not(.//ltx:bibitem)]');
  my $result = $dom;
  my $status = '';
  if (@external) {
    require LaTeXML::Post;
    require LaTeXML::Post::Scan;
    require LaTeXML::Post::MakeBibliography;
    require LaTeXML::Util::ObjectDB;
    my $post = LaTeXML::Post->new(verbosity => -1);
    $post->withState(sub {
      my $doc = LaTeXML::Post::Document->new($dom->cloneNode(1),
        sourceDirectory => $options{source_directory} || '.',
        searchpaths => $options{searchpaths} || [], nocache => 1);
      # Numeric bibliography formatting retains authors/year in the bibblocks.
      # Existing prose bibref/@show remains intact (author-year citations still work).
      $_->setAttribute(citestyle => 'numbers') for $doc->findnodes('//ltx:bibliography[@files][not(.//ltx:bibitem)]');
      my $db = LaTeXML::Util::ObjectDB->new;
      my $scanner = LaTeXML::Post::Scan->new(db => $db);
      $post->ProcessChain($doc, $scanner,
        LaTeXML::Post::MakeBibliography->new(db => $db, scanner => $scanner, split => 0));
      $db->finish;
      $result = $doc->getDocument;
    });
    $status = $post->getStatusMessage;
    die "Bibliography preparation failed: $status\n" if $post->getStatusCode >= 2;
  }
  return ($result, { external_bibliographies => scalar @external, status => $status,
      elapsed_ms => 1000 * (time - $start) });
}
1;
