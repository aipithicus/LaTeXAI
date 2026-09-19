use strict;
use warnings;
use Test::More;
use FindBin;
use File::Spec;
use File::Temp qw(tempdir);
use Cwd qw(abs_path);
use lib File::Spec->catdir($FindBin::Bin, '..', 'tools', 'dev');
use CaptureAudit ();
use CaptureRuntime qw(project_searchpaths);
use XML::LibXML;

chdir File::Spec->catdir($FindBin::Bin, '..') or die $!;
my $temp = abs_path(tempdir('runtime-graphics-XXXXXX', DIR => 'temp/t', CLEANUP => 1));
my $engine = "$temp/engine";

sub fixture {
  my ($variant, $paths, $extra) = @_;
  my $source = "$temp/source $variant/p-tex";
  my $job = "$temp/job-$variant";
  my $receipt = { article => { directory => "$temp/source $variant", slug => 'p' },
    details => { perl => 'C:/perl.exe', arguments => [
      '-I', "$engine/lib", "$engine/bin/latexml", "--path=$source",
      "--log=$job/p.log", "--destination=$job/p.xml", "$source/p.tex"] } };
  my $pis = '';
  for my $entry (@$paths) {
    my $path = $entry;
    $path =~ s{SOURCE}{$source}g;
    $pis .= qq{<?latexml graphicspath="$path"?>};
  }
  my $doc = XML::LibXML->load_xml(string =>
    qq{<?latexml searchpaths="$source"?>$pis<document><!--keep--><p>text</p></document>} . ($extra || ''),
    keep_blanks => 1);
  return ($doc, $receipt, $job);
}

sub project {
  my ($variant, $paths, $extra) = @_;
  return project_searchpaths(fixture($variant, $paths, $extra));
}

my @paths = ('SOURCE/images (v1)', 'SOURCE/figures');
my ($raw, $receipt, $job) = fixture('old', \@paths);
my $bytes = $raw->toString;
my $old = project_searchpaths($raw, $receipt, $job);
my $new = project('new', \@paths);
is($old->{document}->toString, $new->{document}->toString,
  'copied source roots preserve the same graphics directories');
is($raw->toString, $bytes, 'graphics projection never changes the supplied document');
isnt($old->{document}->toString, project('new', ['SOURCE/renamed', 'SOURCE/figures'])->{document}->toString,
  'changed graphics directory remains a difference');
isnt($old->{document}->toString, project('new', [reverse @paths])->{document}->toString,
  'graphics search order remains a difference');
isnt($old->{document}->toString, project('new', [@paths, $paths[0]])->{document}->toString,
  'duplicate graphics metadata remains a difference');
isnt(project('old', ['SOURCE-sibling/images'])->{document}->toString,
  project('new', ['SOURCE-sibling/images'])->{document}->toString,
  'a sibling directory is not inside the source root');
isnt(project('old', ['D:/external-one/images'])->{document}->toString,
  project('new', ['D:/external-two/images'])->{document}->toString,
  'different external graphics roots remain a difference');
like(project('new', ['D:/external/images'])->{document}->toString,
  qr{graphicspath="D:/external/images"}, 'external graphics metadata is untouched');
is(project('old', ['SOURCE'])->{document}->toString,
  project('new', ['SOURCE/'])->{document}->toString, 'the source directory itself projects');
my $windows;
($windows, $receipt, $job) = fixture('new', \@paths);
for my $pi ($windows->findnodes('/processing-instruction("latexml")')) {
  my $data = $pi->getData;
  if ($data =~ /^graphicspath=/) { $data =~ tr{/}{\\}; $pi->setData($data); }
}
is(project_searchpaths($windows, $receipt, $job)->{document}->toString, $old->{document}->toString,
  'native Windows graphic paths use the verified source root');
for my $path ('article-source/images', '') {
  ok(!eval { project('new', [$path]); 1 }, 'relative or empty graphic path is rejected');
}
my ($unknown, $unknown_receipt, $unknown_job) = fixture('new', \@paths,
  '<?latexml graphics_note="SOURCE/images"?>');
like(project_searchpaths($unknown, $unknown_receipt, $unknown_job)->{document}->toString,
  qr{graphics_note="SOURCE/images"}, 'unknown PI fields are untouched');
is($new->{schema}, 'latexai/runtime-path-projection/2', 'projection contract version is explicit');
is(scalar @{$new->{graphics}}, 2, 'each graphics metadata projection has a receipt');
done_testing();
