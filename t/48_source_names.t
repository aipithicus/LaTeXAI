use strict;
use warnings;
use Test::More;
use FindBin;
use Cwd qw(abs_path getcwd);
use File::Spec;
use LaTeXML::Core::SourceRegistry;

my $root = abs_path(File::Spec->catdir($FindBin::Bin, '..'));
my $original_cwd = getcwd();
chdir $root or die $!;
my $base = File::Spec->catdir($root, 't', 'capture');
my $file = File::Spec->catfile($base, 'root.tex');
my $registry = LaTeXML::Core::SourceRegistry->new(root_kind => 'file', root_request => $file);
my $first = $registry->registerSource(kind => 'file', display => $file);
my $second = $registry->registerSource(kind => 'file', display => $file);
isnt($first, $second, 'reopening the same path retains distinct source identities');
my @cases = (
  [$first, 'root.tex'],
  [$second, 'root.tex'],
  [$registry->registerSource(kind => 'file', display => File::Spec->catfile($base, 'parts', 'chapter.tex')),
    'parts/chapter.tex'],
  [$registry->registerSource(kind => 'file', display => File::Spec->catfile($root, 't', 'other.tex')),
    '../other.tex'],
  [$registry->registerSource(kind => 'file', display => ''), ''],
  [$registry->registerSource(kind => 'virtual', display => 'generated\\helper'), 'generated/helper'],
  [$registry->registerSource(kind => 'literal', display => 'ignored'), 'literal'],
  ['unknown-source', undef],
);
for my $repeat (1 .. 3) {
  for my $case (@cases) {
    is($registry->sourceName($case->[0]), $case->[1], "lookup $repeat preserves name for $case->[0]");
  }
}

# getEntry exposes descriptors. A retained name must reflect descriptor/base
# changes, and two registries must never share a source-id cache.
my $entry = $registry->getEntry($first);
$entry->{display} = File::Spec->catfile($base, 'renamed.tex');
is($registry->sourceName($first), 'renamed.tex', 'changed display path is reflected');
is($registry->sourceName($second), 'root.tex', 'another occurrence of the original path stays independent');
$registry->{base} = File::Spec->catdir($root, 't');
is($registry->sourceName($first), 'capture/renamed.tex', 'changed base is reflected');
$registry->{base} = $base;
is($registry->sourceName($first), 'renamed.tex', 'restored base is reflected');
$entry->{kind} = 'literal';
is($registry->sourceName($first), 'literal', 'changed source kind bypasses a previous file name');
$entry->{kind} = 'file';
is($registry->sourceName($first), 'renamed.tex', 'restored file kind retains its correct name');
my $other = LaTeXML::Core::SourceRegistry->new(
  root_kind => 'file', root_request => File::Spec->catfile($root, 't', 'other-root.tex'));
my $other_id = $other->registerSource(kind => 'file', display => $file);
is($other->sourceName($other_id), 'capture/root.tex', 'another registry uses its own base');

# Registered file paths are absolute. Descriptors replaced with relative paths
# remain sensitive to cwd, so those lookups must retain ordinary resolution.
$entry->{display} = 'relative.tex';
is($registry->sourceName($first), '../../relative.tex', 'relative descriptor resolves from the current directory');
chdir File::Spec->catdir($root, 't') or die $!;
is($registry->sourceName($first), '../relative.tex', 'relative descriptor follows a changed current directory');
chdir $root or die $!;
is($registry->sourceName($first), '../../relative.tex', 'relative descriptor follows a restored directory');

SKIP: {
  my $system = $ENV{SystemRoot} || $ENV{SYSTEMROOT};
  my ($volume) = File::Spec->splitpath($root);
  my ($other_volume) = File::Spec->splitpath($system || '');
  skip 'Needs Windows directories on two drives', 2
    unless $^O eq 'MSWin32' && $system && -d $system && lc($volume) ne lc($other_volume);
  $entry->{display} = '\\capture-root-relative.tex';
  my $expected = File::Spec->abs2rel($entry->{display}, $base);
  $expected =~ s!\\!/!g;
  is($registry->sourceName($first), $expected, 'rooted descriptor resolves on the current drive');
  chdir $system or die $!;
  $expected = File::Spec->abs2rel($entry->{display}, $base);
  $expected =~ s!\\!/!g;
  is($registry->sourceName($first), $expected, 'rooted descriptor follows a changed current drive');
  chdir $root or die $!;
}
chdir $original_cwd or die $!;
done_testing();
