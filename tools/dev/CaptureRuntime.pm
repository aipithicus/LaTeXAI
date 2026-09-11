package CaptureRuntime;
use strict;
use warnings;
use base qw(Exporter);
use File::Spec;
use File::Basename qw(dirname);
use MIME::Base64 qw(decode_base64);
our @EXPORT_OK = qw(canonical_path runtime_contract project_searchpaths);

# Paths are addresses, not implementations. Do not case-fold filenames or follow
# today's filesystem when interpreting a retained snapshot's historical address.
sub canonical_path {
  my ($path) = @_;
  return undef unless defined $path;
  $path =~ s{\\}{/}g;
  my $prefix = $path =~ s{^([A-Za-z]:)/}{} ? "$1/"
    : $path =~ s{^//}{} ? '//' : $path =~ s{^/}{} ? '/' : '';
  my @parts;
  for my $part (split m{/+}, $path) {
    next if $part eq '' || $part eq '.';
    if ($part eq '..' && @parts && $parts[-1] ne '..') { pop @parts; }
    else { push @parts, $part; }
  }
  return $prefix . join('/', @parts);
}

sub _snapshot_text {
  my ($state, $relative) = @_;
  my $hash = $state->{files}{$relative} or die "Unrecorded runtime input: $relative\n";
  my $absolute = "$state->{root}/$relative";
  my $text;
  if (-f $absolute && CaptureAudit::file_hash($absolute) eq $hash) {
    $text = CaptureAudit::read_raw($absolute);
  }
  elsif ($state->{uncommitted_files_base64} && exists $state->{uncommitted_files_base64}{$relative}) {
    $text = decode_base64($state->{uncommitted_files_base64}{$relative});
  }
  else {
    my $commit = $state->{engine_commit} || '';
    die "No retained runtime source for $relative\n" unless $commit =~ /^[a-f0-9]{40}$/;
    $text = CaptureAudit::_git('-C', $state->{root}, 'show', "$commit:$relative");
  }
  require Digest::SHA;
  die "Runtime source hash mismatch: $relative\n" unless Digest::SHA::sha256_hex($text) eq $hash;
  return $text;
}

sub runtime_contract {
  my ($state) = @_;
  my %environment = %{$state->{environment} || {}};
  my $workers = delete $environment{LATEXAI_AUDIT_JOBS};
  my %evidence;
  $environment{PERL_ROOT} = canonical_path($environment{PERL_ROOT}) if exists $environment{PERL_ROOT};
  my $command = $environment{LATEXML_KPSEWHICH};
  if (defined $command) {
    my $root = canonical_path($state->{root});
    my $path = canonical_path($command);
    $environment{LATEXML_KPSEWHICH} = $path;
    if (index($path, "$root/") == 0) {
      my $relative = substr($path, length($root) + 1);
      my $source = _snapshot_text($state, $relative);
      $source =~ s/\r\n/\n/g;
      # Recognize the complete launcher, not just a command somewhere inside it.
      # Extra commands, Perl switches and arguments are not equivalent wrappers.
      if ($source =~ /\A\@echo off\nif "%PERL_ROOT%"=="" \(\n  echo [^\n&|<>]+ 1>&2\n  exit \/b 1\n\)\n"%PERL_ROOT%\\perl\\bin\\perl\.exe" "%~dp0([^"\n]+)" %\*\n?\z/) {
        my $target = canonical_path(dirname($relative) . '/' . $1);
        die "Runtime launcher escapes checkout\n" if $target =~ m{^\.\.(?:/|$)};
        die "Unrecorded launcher target: $target\n" unless $state->{files}{$target};
        $environment{LATEXML_KPSEWHICH} = { kind => 'checkout-perl-launcher', target => $target };
        $evidence{kpsewhich} = { launcher => $relative, launcher_sha256 => $state->{files}{$relative},
          target => $target, target_sha256 => $state->{files}{$target} };
      }
    }
  }
  return { schema => 'latexai/runtime-contract/1', identity => \%environment,
    evidence => \%evidence, execution => { workers => $workers } };
}

sub _invocation {
  my ($receipt, $job_directory) = @_;
  my @args = @{$receipt->{details}{arguments} || []};
  die "Missing recorded invocation\n" unless @args >= 5 && shift(@args) eq '-I';
  my $lib = canonical_path(shift @args);
  die "Unrecognized engine library\n" unless $lib =~ s{/lib$}{};
  my $engine = $lib;
  die "Unrecognized engine entrypoint\n" unless canonical_path(shift @args) eq "$engine/bin/latexml";
  my $source = canonical_path("$receipt->{article}{directory}/$receipt->{article}{slug}-tex");
  my $job = canonical_path($job_directory);
  my (@options, @paths, @roles);
  my $entry = pop @args;
  $entry = "$source/$entry" unless $entry =~ m{^(?:[A-Za-z]:[/\\]|/)};
  $entry = canonical_path($entry);
  die "Entry point escapes source tree\n" unless index($entry, "$source/") == 0;
  for my $arg (@args) {
    if ($arg =~ /^--path=(.*)$/s) {
      my $path = canonical_path($1);
      push @paths, $path;
      # Versioned interpretation of the repository's former and current preload
      # directory roles. Only an explicit historical projection invokes this.
      my $role = $path eq $source ? 'article-source'
        : ($path eq "$engine/private/scripts" || $path eq "$engine/scripts/preloads") ? 'engine-preloads' : $path;
      push @roles, $role;
      push @options, { searchpath => $role };
    }
    elsif ($arg =~ /^--(log|destination)=(.*)$/s) {
      my ($kind, $path) = ($1, canonical_path($2));
      die "Output address outside recorded job\n" unless index($path, "$job/") == 0;
      push @options, { output => $kind };
    }
    else { push @options, $arg; }
  }
  my (%seen, @ordered, @ordered_roles);
  for my $i (reverse 0 .. $#paths) {
    next if $seen{$paths[$i]}++;
    push @ordered, $paths[$i]; push @ordered_roles, $roles[$i];
  }
  return { identity => { engine => $engine, source => $source, entry => $entry, options => \@options,
      perl => canonical_path($receipt->{details}{perl}) }, paths => \@ordered, roles => \@ordered_roles };
}

sub project_searchpaths {
  my ($document, $receipt, $job_directory) = @_;
  my $invocation = _invocation($receipt, $job_directory);
  my $copy = $document->cloneNode(1);
  my @pis = grep { $_->getData =~ /^searchpaths=/ } $copy->findnodes('/processing-instruction("latexml")');
  die "Expected one top-level searchpaths instruction\n" unless @pis == 1;
  my $data = $pis[0]->getData;
  die "Malformed searchpaths instruction\n" unless $data =~ /^searchpaths="([^"<>]*)"$/;
  my @paths = map { canonical_path($_) } split /,/, $1;
  die "Searchpaths instruction disagrees with recorded invocation\n"
    unless CaptureAudit::object_hash(\@paths) eq CaptureAudit::object_hash($invocation->{paths});
  $pis[0]->setData('searchpaths="' . join(',', @{$invocation->{roles}}) . '"');
  return { document => $copy, identity => $invocation->{identity}, before => $data, after => $pis[0]->getData };
}

1;
