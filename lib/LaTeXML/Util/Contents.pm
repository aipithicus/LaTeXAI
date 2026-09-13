# Shared construction of manuscript TOC links for etoc and titletoc.
# Uses the existing LaTeXML TOC vocabulary. No parser or postprocessor changes.
package LaTeXML::Util::Contents;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT_OK=qw(contents_level contents_select fill_local_contents fill_partial_contents);
my %levels=(part=>-1,chapter=>0,section=>1,appendix=>1,subsection=>2,
 subsubsection=>3,paragraph=>4,subparagraph=>5);
sub contents_level {return $levels{$_[0]};}
sub contents_select {
 my ($low,$high)=@_;
 return join(' | ',map {'ltx:'.$_} grep {$levels{$_}>=$low && $levels{$_}<=$high}
  qw(part chapter section appendix subsection subsubsection paragraph subparagraph));
}
sub _fill {
 my ($doc,$toc,$nodes)=@_;
 my @roots;my %lists;my %types=map {$_=>1} split(/\s*\|\s*/,$toc->getAttribute('select')||'');
 for my $node (@$nodes) {
  my $type=$node->localname;
  next unless exists $levels{$type} && $types{'ltx:'.$type};
  next unless ($node->getAttribute('inlist')||'') =~ /(?:^|\s)toc(?:\s|$)/;
  my $id=$node->getAttribute('xml:id');next unless $id;
  my @children;my $entry=['ltx:tocentry',{class=>'ltx_tocentry_'.$type},
   ['ltx:ref',{idref=>$id,show=>'toctitle'}]];
  my $parent=$node->parentNode;my $target=\@roots;
  while ($parent && $parent->nodeType==1) {
   if (my $slot=$lists{$parent->nodePath}) {
    if (!$slot->[1]) {$slot->[1]=['ltx:toclist',{}];push @{$slot->[0]},$slot->[1];}
    $target=$slot->[1];last;
   }
   $parent=$parent->parentNode;
  }
  push @$target,$entry;
  $lists{$node->nodePath}=[$entry,undef];
 }
 $doc->appendTree($toc,['ltx:toclist',{},@roots]);
 return;
}
sub fill_local_contents {
 my ($doc)=@_;
 for my $toc ($doc->findnodes('//ltx:TOC[@class="ltx_etoc"]')) {
  my $root=$toc->parentNode;
  while ($root && $root->nodeType==1 && !exists($levels{$root->localname}) && $root->localname ne 'document') {$root=$root->parentNode;}
  next unless $root;
  my $id=$root->getAttribute('xml:id');$toc->setAttribute(scope=>$id||'current');
  _fill($doc,$toc,[$doc->findnodes('.//*',$root)]);
 }
 return;
}
sub fill_partial_contents {
 my ($doc)=@_;
 my @all=$doc->findnodes('//*');
 for my $toc ($doc->findnodes('//ltx:TOC[@class="ltx_titletoc"]')) {
  my ($range)=($toc->getAttribute('scope')||'') =~ /^ttl\.(\d+)\./;next unless defined $range;
  my $active=0;my @selected;my $first;
  for my $node (@all) {
   if (my ($kind)=($node->getAttribute('xml:id')||'') =~ /^ttl\.\Q$range\E\.(start|stop)\./) {$active=$kind eq 'start';$first||=$node->getAttribute('xml:id') if $active;next;}
   push @selected,$node if $active;
  }
  $toc->setAttribute(scope=>$first) if $first;
  _fill($doc,$toc,\@selected);
 }
 return;
}
1;
