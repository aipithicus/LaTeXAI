package LaTeXAI::Post::Markdown;
use strict;
use warnings;
use utf8;
use Time::HiRes qw(time);
use File::Spec;

our $VERSION = '0.1';
my $LTX = 'http://dlmf.nist.gov/LaTeXML';
my $XML = 'http://www.w3.org/XML/1998/namespace';
my %SECTION = map { $_ => 1 } qw(part chapter section subsection subsubsection paragraph subparagraph appendix);
my %SKIP = map { $_ => 1 } qw(resource tags toccaption toctitle TOC navigation pagination date indexmark);
my %TRANSPARENT = map { $_ => 1 } qw(document text cite inline-block biblist tbody thead tfoot personname
  bib-date bib-edition bib-language bib-organization bib-part bib-place bib-publisher bib-title bib-type);

sub new { my ($class, %options) = @_; return bless { toc => 1, %options }, $class; }
sub trim { my ($s) = @_; $s //= ''; $s =~ s/^\s+|\s+$//g; return $s; }
sub escape {
  my ($s) = @_;
  $s //= '';
  $s =~ s/([\\`*_\[\]<>#!|\$])/\\$1/g;
  return $s;
}
sub _id { return $_[0]->getAttributeNS($XML, 'id') || ''; }
sub _children {
  my ($node) = @_;
  return grep { $_->nodeType == 1 } $node->childNodes;
}
sub _child {
  my ($node, $name) = @_;
  for my $child (_children($node)) {
    return $child if ($child->namespaceURI || '') eq $LTX && $child->localname eq $name;
  }
  return;
}
sub _primary {
  my ($node) = @_;
  # The first non-branch child may also be prose marked as math.
  if (my $math = _child($node, 'Math')) { return $math; }
  for my $child (_children($node)) {
    return $child if ($child->namespaceURI || '') eq $LTX && $child->localname ne 'MathBranch';
  }
  return;
}
sub _issue {
  my ($self, $kind, $node, $detail) = @_;
  push @{$self->{issues}}, { kind => $kind, id => _id($node), element => $node->nodeName, detail => $detail };
}

# No Post::Document construction, global XPath query, or DOM mutation here.
# The index strategy discovers metadata first and resolves refs on encounter.
# The deferred strategy discovers the same metadata during emission and stores
# typed reference fragments. Both share selection and Markdown serialization.
sub project {
  my ($self, $dom, %options) = @_;
  my $root = $dom->documentElement;
  die "Expected ltx:document\n" unless $root && $root->localname eq 'document'
    && ($root->namespaceURI || '') eq $LTX;
  my $strategy = $options{strategy} || 'deferred';
  die "Unknown traversal '$strategy'\n" unless $strategy =~ /^(deferred|indexed)$/;
  my $run = bless { %$self, strategy => $strategy, records => {}, targets => {},
    headings => [], slugs => {}, notes => [], bibliography => [], bibkeys => {},
    issues => [], math => [], counters => { index_visits => 0, emit_visits => 0,
      label_visits => 0, references => 0, deferred_references => 0, metadata_records => 0 } }, ref $self;
  my $start = time;
  if ($strategy eq 'indexed') {
    $run->_walk($root, [], {}, 'index');
    $run->_heading_slugs;
  }
  my $indexed = time;
  my @parts;
  $run->_walk($root, \@parts, {}, 'emit');
  my $walked = time;
  $run->_heading_slugs if $strategy eq 'deferred';
  my @final;
  if ($run->{front}) { push @final, @{$run->{front}}; }
  if ($run->{toc} && @{$run->{headings}}) {
    push @final, [gap => 2], "## Contents", [gap => 2];
    push @final, join "\n", map {
      ('  ' x ($_->{level} - 2)) . '- [' . $_->{label} . '](#' . $_->{slug} . ')'
    } @{$run->{headings}};
    push @final, [gap => 2];
  }
  push @final, @parts;
  if (@{$run->{notes}}) {
    push @final, [gap => 2], '## Notes', [gap => 2];
    for my $note (@{$run->{notes}}) {
      push @final, '[^' . $note->{number} . ']: ' . $run->_serialize($note->{parts}, 1), [gap => 2];
    }
  }
  push @final, @{$run->{bibliography}};
  my $markdown = $run->_serialize(\@final) . "\n";
  my $ended = time;
  return { markdown => $markdown, report => { schema => 'latexai/markdown-projection/0.1',
      strategy => $strategy, counters => $run->{counters},
      timings_ms => { index => 1000 * ($indexed - $start), walk => 1000 * ($walked - $indexed),
        finalize => 1000 * ($ended - $walked), total => 1000 * ($ended - $start) },
      headings => [map { +{ label => $_->{label}, slug => $_->{slug}, level => $_->{level} } } @{$run->{headings}}],
      math => $run->{math}, issues => $run->{issues}, bibliography_entries => $run->{bibcount} || 0 } };
}

# Allocate renderer-style anchors in final manuscript order, including synthetic
# headings and the bibliography moved after notes. Both strategies do this once.
sub _heading_slugs {
  my ($self) = @_;
  my @headings = (grep { !$_->{end_matter} } @{$self->{headings}});
  push @headings, { name => 'notes', label => 'Notes', level => 2 } if $self->{notecount};
  push @headings, grep { $_->{end_matter} } @{$self->{headings}};
  $self->{headings} = \@headings;
  my @reserved = ({ label => $self->{document_label} || 'Untitled' });
  push @reserved, { label => 'Contents' } if $self->{toc} && @headings;
  for my $r (@reserved, @headings) {
    my $slug = lc $r->{label};
    $slug =~ s/\\//g; $slug =~ s/[^\p{L}\p{N}_\-\s]//g; $slug =~ s/\s+/-/g;
    $slug ||= 'section';
    my $base = $slug;
    my $suffix = $self->{slug_suffix}{$base} || 0;
    $slug = $base . '-' . ++$suffix while $self->{slugs}{$slug};
    $self->{slug_suffix}{$base} = $suffix;
    $self->{slugs}{$slug} = 1; $r->{slug} = $slug;
  }
}

# Small titles are consumed once and cached. Their fragments are reused by the
# heading, TOC and reference labels. Math descendants are never visited.
sub _label {
  my ($self, $node) = @_;
  $self->{counters}{label_visits}++;
  if ($node->nodeType == 3 || $node->nodeType == 4) {
    my $s = $node->data; $s =~ s/\s+/ /g; return escape($s);
  }
  return '' unless $node->nodeType == 1;
  my $name = $node->localname;
  return '' if $SKIP{$name};
  if ($name eq 'Math') {
    my $tex = $node->getAttribute('tex') || '';
    push @{$self->{math}}, { id => _id($node), mode => 'inline', carrier => 'tex', context => 'label' };
    if (!length $tex) { $self->_issue('missing-math-tex', $node, 'No tex carrier'); $tex = '\text{[math unavailable]}'; }
    return $self->{math_renderer} ? $self->{math_renderer}->($node, 0) : '$' . $tex . '$';
  }
  if ($name eq 'MathFork') {
    my $primary = _primary($node); return $primary ? $self->_label($primary) : '\[math unavailable\]';
  }
  if ($name eq 'ref' || $name eq 'bibref') {
    $self->_issue('reference-in-title', $node, 'Title references are explicit residue in this prototype');
    return '\[' . escape($node->getAttribute('labelref') || $node->getAttribute('bibrefs') || _id($node)) . '\]';
  }
  my $s = join '', map { $self->_label($_) } $node->childNodes;
  return escape($node->getAttribute('open')) . $s . escape($node->getAttribute('close')) if $name eq 'tag';
  return $s;
}
sub _register {
  my ($self, $node, $ctx) = @_;
  my $key = $node->unique_key;
  return $self->{records}{$key} if $self->{records}{$key};
  my $name = $node->localname;
  my $id = _id($node);
  return unless $id || $node->hasAttribute('labels') || $SECTION{$name}
    || $name =~ /^(document|abstract|bibliography|bibitem|note|theorem|proof|float|figure|table)$/;
  my $r = { id => $id, name => $name, tags => {} };
  $self->{records}{$key} = $r;
  $self->{counters}{metadata_records}++;
  for my $alias (grep { length } $id, split /\s+/, ($node->getAttribute('labels') || '')) {
    if ($self->{targets}{$alias}) { $self->_issue('duplicate-target', $node, $alias); }
    else { $self->{targets}{$alias} = $r; }
  }
  if (my $tags = _child($node, 'tags')) {
    for my $tag (_children($tags)) {
      my $role = $tag->getAttribute('role') || 'display';
      $r->{tags}{$role} = trim($self->_label($tag));
      $r->{author_year_label} = 1 if ($tag->getAttribute('class') || '') eq 'ltx_bib_author-year';
    }
  }
  if (my $title = _child($node, 'title')) { $r->{label} = trim($self->_label($title)); }
  $self->{document_label} = $r->{label} if $name eq 'document';
  if ($name eq 'abstract') { $r->{label} ||= escape($node->getAttribute('name') || 'Abstract'); }
  if ($SECTION{$name} || $name eq 'abstract' || $name eq 'bibliography') {
    $r->{label} ||= ucfirst $name;
    $r->{level} = ($ctx->{section_depth} || 0) + 2;
    $r->{level} = 6 if $r->{level} > 6;
    $r->{end_matter} = $name eq 'bibliography' || $ctx->{in_bibliography};
    push @{$self->{headings}}, $r;
  }
  if ($name eq 'bibitem') {
    $r->{number} = ++$self->{bibcount};
    my $bibkey = $node->getAttribute('key');
    $self->{bibkeys}{$bibkey} = $r;
  }
  if ($name eq 'note') { $r->{number} = ++$self->{notecount}; }
  return $r;
}
sub _descend {
  my ($self, $node, $sink, $ctx, $mode, @skip) = @_;
  my %skip = map { $_ => 1 } @skip;
  for my $child ($node->childNodes) {
    next if $child->nodeType == 1 && $skip{$child->localname};
    $self->_walk($child, $sink, $ctx, $mode);
  }
}
sub _walk {
  my ($self, $node, $sink, $ctx, $mode) = @_;
  no warnings 'recursion';
  $self->{counters}{$mode eq 'index' ? 'index_visits' : 'emit_visits'}++;
  my $emit = $mode eq 'emit';
  my $type = $node->nodeType;
  if ($type == 3 || $type == 4) {
    if ($emit) { my $s = $node->data; $s =~ s/\s+/ /g; push @$sink, escape($s); }
    return;
  }
  return unless $type == 1;
  my $name = $node->localname;
  my $ns = $node->namespaceURI || '';
  return if $ns =~ m{/capture$};
  return if $SKIP{$name} && $ns eq $LTX;
  if ($ns ne $LTX) {
    if ($emit) { $self->_issue('foreign-element', $node, $ns); push @$sink, '\[foreign ' . escape($node->nodeName) . '\]'; }
    return;
  }
  my $r = ($mode eq 'index' || $self->{strategy} eq 'deferred')
    ? $self->_register($node, $ctx) : $self->{records}{$node->unique_key};
  if ($name eq 'Math') {
    if ($emit) {
      my $display = $ctx->{display} || ($node->getAttribute('mode') || '') eq 'display';
      my $tex = $node->getAttribute('tex') || '';
      push @{$self->{math}}, { id => _id($node), mode => $display ? 'display' : 'inline', carrier => 'tex' };
      if (!length $tex) { $self->_issue('missing-math-tex', $node, 'No tex carrier'); $tex = '\text{[math unavailable]}'; }
      my $math = $self->{math_renderer} ? $self->{math_renderer}->($node, $display)
        : ($display ? "\$\$\n$tex\n\$\$" : '$' . $tex . '$');
      push @$sink, [gap => 2] if $display;
      push @$sink, $math;
      push @$sink, [gap => 2] if $display;
    }
    return;
  }
  if ($name eq 'MathFork') {
    if (my $primary = _primary($node)) { $self->_walk($primary, $sink, $ctx, $mode); }
    elsif ($emit) { $self->_issue('missing-primary-math', $node, 'No primary Math in MathFork'); push @$sink, '\[math fork unavailable\]'; }
    return;
  }
  if ($name eq 'picture' || $name eq 'ERROR') {
    if ($emit) {
      $self->_issue('opaque-element', $node, 'Retained in source XML');
      push @$sink, [gap => 2], '\[' . escape($name . ' ' . _id($node)) . '\]', [gap => 2];
    }
    return;
  }
  if ($name eq 'ref' || $name eq 'bibref') {
    if ($emit) {
      my $spec = { kind => $name, id => _id($node), key => $node->getAttribute('labelref') || $node->getAttribute('idref'),
        href => $node->getAttribute('href'), show => $node->getAttribute('show'), bibkeys => $node->getAttribute('bibrefs'),
        text => '',
        phrases => [map { $_->textContent } grep { $_->localname eq 'bibrefphrase' } _children($node)] };
      # Explicit text is rendered from children, rather than _label's residue policy for a ref itself.
      $spec->{text} = trim(join '', map { $self->_label($_) } $node->childNodes) if $name eq 'ref';
      $self->{counters}{references}++;
      if ($self->{strategy} eq 'indexed') { push @$sink, $self->_reference($spec); }
      else { push @$sink, [reference => $spec]; $self->{counters}{deferred_references}++; }
    }
    return;
  }
  if ($name eq 'document') {
    if ($emit) { $self->{front} = [[gap => 2], '# ' . ($r->{label} || 'Untitled'), [gap => 2]]; }
    $self->_descend($node, $sink, $ctx, $mode, 'title'); return;
  }
  if ($name eq 'creator') {
    my @parts; $self->_descend($node, \@parts, $ctx, $mode);
    push @{$self->{front}}, @parts, [gap => 2] if $emit; return;
  }
  if ($SECTION{$name} || $name eq 'abstract' || $name eq 'bibliography') {
    my $out = $name eq 'bibliography' ? $self->{bibliography} : $sink;
    push @$out, [gap => 2], ('#' x $r->{level}) . ' ' . $r->{label}, [gap => 2] if $emit;
    $self->_descend($node, $out, { %$ctx, in_bibliography => $name eq 'bibliography' || $ctx->{in_bibliography},
      section_depth => ($ctx->{section_depth} || 0) + ($SECTION{$name} ? 1 : 0) }, $mode, 'title');
    if ($emit && $name eq 'bibliography' && !@{[grep { $_->localname eq 'biblist' || $_->localname eq 'bibitem' } _children($node)]}) {
      $self->_issue('external-bibliography', $node, $node->getAttribute('files'));
      push @$out, 'Bibliography unavailable: ' . escape($node->getAttribute('files')), [gap => 2];
    }
    return;
  }
  if ($name eq 'bibitem') {
    push @$sink, [gap => 2], '[' . $r->{number} . '] ' if $emit;
    push @$sink, $r->{tags}{refnum} . '. ' if $emit && $r->{author_year_label};
    $self->_descend($node, $sink, $ctx, $mode);
    push @$sink, [gap => 2] if $emit; return;
  }
  if ($name eq 'bibblock') {
    return if ($node->getAttribute('class') || '') eq 'ltx_bib_cited';
    $self->_descend($node, $sink, $ctx, $mode); push @$sink, ' ' if $emit; return;
  }
  if ($name eq 'note') {
    my @parts; $self->_descend($node, \@parts, $ctx, $mode);
    if ($emit) { push @{$self->{notes}}, { number => $r->{number}, parts => \@parts }; push @$sink, '[^' . $r->{number} . ']'; }
    return;
  }
  if ($name =~ /^(theorem|proof)$/) {
    push @$sink, [gap => 2], '**' . ($r->{label} || ucfirst $name) . '**', [gap => 2] if $emit;
    $self->_descend($node, $sink, $ctx, $mode, 'title'); push @$sink, [gap => 2] if $emit; return;
  }
  if ($name eq 'equation' || $name eq 'equationgroup') {
    push @$sink, [gap => 2] if $emit;
    $self->_descend($node, $sink, {%$ctx, display => 1}, $mode);
    push @$sink, [gap => 2], ($r->{tags}{display} || '(' . $r->{tags}{refnum} . ')'), [gap => 2]
      if $emit && $r && ($r->{tags}{display} || $r->{tags}{refnum});
    return;
  }
  if ($name =~ /^(itemize|enumerate|description)$/) {
    push @$sink, [gap => 2] if $emit;
    $self->_descend($node, $sink, {%$ctx, list => $name, list_depth => ($ctx->{list_depth} || 0) + 1, item_counter => \(my $n = 0)}, $mode);
    push @$sink, [gap => 2] if $emit; return;
  }
  if ($name eq 'item') {
    my @parts; $self->_descend($node, \@parts, {%$ctx, in_item => 1}, $mode);
    if ($emit) { my $prefix = ($ctx->{list} || '') eq 'enumerate' ? ++${$ctx->{item_counter}} . '. ' : '- ';
      push @$sink, [item => { prefix => $prefix, parts => \@parts }]; }
    return;
  }
  if ($name eq 'tabular') {
    my $table = { rows => [], node => $node };
    $self->_descend($node, [], {%$ctx, table => $table}, $mode);
    push @$sink, [gap => 2], [table => $table], [gap => 2] if $emit; return;
  }
  if ($name eq 'tr' && $ctx->{table}) {
    my $row = []; push @{$ctx->{table}{rows}}, $row if $emit;
    $self->_descend($node, [], {%$ctx, row => $row}, $mode); return;
  }
  if (($name eq 'td' || $name eq 'th') && $ctx->{row}) {
    my @parts; $self->_descend($node, \@parts, {%$ctx, display => 0}, $mode);
    push @{$ctx->{row}}, { parts => \@parts, rows => $node->getAttribute('rowspan') || 1,
      cols => $node->getAttribute('colspan') || 1, node => $node } if $emit; return;
  }
  if ($name eq 'graphics') {
    if ($emit) {
      my $path = $node->getAttribute('graphic') || $node->getAttribute('src');
      $path = File::Spec->rel2abs($path, $self->{asset_root}) if $self->{asset_root};
      $path =~ tr{\\}{/}; $path =~ s/([<>\r\n])/sprintf('%%%02X',ord($1))/ge;
      my $image = $path =~ /\.(png|jpe?g|gif|webp|svg)$/i;
      $self->_issue('unconverted-asset', $node, $path) unless $image;
      push @$sink, [gap => 2], ($image ? '![Figure]' : '[Figure asset]') . '(<'. $path . '>)', [gap => 2];
    }
    return;
  }
  if ($name eq 'break') { push @$sink, "  \n" if $emit; return; }
  if ($name eq 'tag') {
    push @$sink, escape($node->getAttribute('open')) if $emit;
    $self->_descend($node, $sink, $ctx, $mode);
    push @$sink, escape($node->getAttribute('close')) if $emit; return;
  }
  if ($name eq 'listingline') {
    my @parts; $self->_descend($node, \@parts, $ctx, $mode);
    push @$sink, [gap => 1], [quote_line => \@parts], [gap => 1] if $emit;
    return;
  }
  if ($name eq 'emph' || $name eq 'sup' || $name eq 'sub' || ($name eq 'text' && ($node->getAttribute('font') || '') =~ /bold|italic/)) {
    my @parts; $self->_descend($node, \@parts, $ctx, $mode);
    my $mark = $name eq 'sup' ? '^' : $name eq 'sub' ? '~'
      : ($name eq 'text' && $node->getAttribute('font') =~ /bold/) ? '**' : '*';
    push @$sink, [style => { mark => $mark, parts => \@parts }] if $emit;
    return;
  }
  my $block = $name =~ /^(p|para|contact|figure|table|float|caption|listing|listingline|keywords|pubnote|quote|verbatim)$/;
  if ($name eq 'verbatim') {
    if ($emit) { my $s=$node->textContent; my $f='```'; $f.='`' while index($s,$f)>=0;
      push @$sink,[gap=>2],"$f\n$s\n$f",[gap=>2]; } return;
  }
  if (!$TRANSPARENT{$name} && !$block) {
    if ($emit) { $self->_issue('unhandled-element', $node, 'Children retained'); push @$sink, '\[unhandled ' . escape($name) . '\] '; }
  }
  push @$sink, [gap => 2] if $emit && $block;
  $self->_descend($node, $sink, $ctx, $mode);
  push @$sink, [gap => 2] if $emit && $block;
}

sub _reference {
  my ($self, $spec) = @_;
  if ($spec->{kind} eq 'bibref') {
    my @values;
    for my $key (split /,/, ($spec->{bibkeys} || '')) {
      $key = trim($key);
      my $r = $self->{bibkeys}{$key};
      if (!$r) { push @{$self->{issues}}, { kind => 'unresolved-citation', key => $key }; push @values, '@' . escape($key); next; }
      if (($spec->{show} || '') =~ /Authors/) {
        my $authors = $r->{tags}{authors} || $r->{tags}{fullauthors};
        my $year = $r->{tags}{year};
        if ($authors && $year) {
          my @p = map { escape($_) } @{$spec->{phrases}};
          my $label = $spec->{show};
          $label =~ s/Authors|Year|Phrase(\d+)/$& eq 'Authors' ? $authors : $& eq 'Year' ? $year : ($p[$1-1] \/\/ '')/ge;
          push @values, $label; next;
        }
      }
      push @values, $r->{number};
    }
    return join(($spec->{show} || '') =~ /Authors/ ? '; ' : ', ', @values);
  }
  if ($spec->{href}) {
    my $url = $spec->{href}; $url =~ s/([<>\r\n])/sprintf('%%%02X',ord($1))/ge;
    return '[' . ($spec->{text} || escape($spec->{href})) . '](<' . $url . '>)';
  }
  my $key = $spec->{key} || '';
  my $r = $self->{targets}{$key};
  if (!$r) { push @{$self->{issues}}, { kind => 'unresolved-reference', key => $key }; return $spec->{text} || '\[reference: ' . escape($key) . '\]'; }
  my $text = $spec->{text} || (($spec->{show} || '') =~ /title/ ? $r->{label} : '')
    || $r->{tags}{refnum} || $r->{label} || escape($key);
  return $r->{slug} ? "[$text](#$r->{slug})" : $text;
}
sub _serialize {
  my ($self, $parts, $indent, $edges) = @_;
  my (@out, $gap); $gap = 0;
  for my $part (@$parts) {
    my $s;
    if (!ref $part) { $s = $part; }
    else {
      my ($kind, $value) = @$part;
      if ($kind eq 'gap') { $gap = $value if $value > $gap; next; }
      if ($kind eq 'reference') { $s = $self->_reference($value); }
      elsif ($kind eq 'style') {
        $s = $self->_serialize($value->{parts}, 0, 1);
        $s =~ s/^(\s*)(.*?)(\s*)$/$1$value->{mark}$2$value->{mark}$3/s if length trim($s);
      }
      elsif ($kind eq 'quote_line') {
        $s = $self->_serialize($value); $s =~ s/\n/\n> /g; $s = '> ' . $s;
      }
      elsif ($kind eq 'item') {
        $s = $self->_serialize($value->{parts}); $s =~ s/\n/"\n" . (' ' x length($value->{prefix}))/ge;
        $s = $value->{prefix} . $s; $gap = 1 if $gap < 1;
      }
      elsif ($kind eq 'table') { $s = $self->_table_text($value); }
      else { die "Unknown Markdown fragment $kind\n"; }
    }
    next unless defined $s && length $s;
    next if $s =~ /^\s+$/ && ($gap || (!@out && !$edges));
    if ($gap) {
      $out[-1] =~ s/[ \t]+$// if @out;
      push @out, "\n" x $gap if @out;
      $s =~ s/^\s+//;
      $gap = 0;
    }
    $s =~ s/^ +// unless @out || $edges;
    $s =~ s/^ +// if @out && $out[-1] =~ / $/;
    push @out, $s;
  }
  my $s = join '', @out;
  $s =~ s/[ \t]+$// unless $edges;
  $s =~ s/\n/\n    /g if $indent;
  return $s;
}
sub _table_text {
  my ($self, $table) = @_;
  my (@grid, $width); $width = 0;
  my $r = 0;
  for my $row (@{$table->{rows}}) {
    my $c = 0;
    for my $cell (@$row) {
      $c++ while defined $grid[$r][$c];
      my ($rs, $cs) = @$cell{qw(rows cols)};
      die "Invalid table span\n" unless $rs =~ /^\d+$/ && $cs =~ /^\d+$/ && $rs > 0 && $cs > 0 && $rs <= 1000 && $cs <= 1000;
      my $value = $self->_serialize($cell->{parts});
      $value =~ s/\s*\n+\s*/ /g;
      $value =~ s/(?<!\\)\|/\\|/g;
      $self->_issue('flattened-table-span', $cell->{node}, "rowspan=$rs colspan=$cs") if $rs > 1 || $cs > 1;
      for my $dr (0 .. $rs-1) { for my $dc (0 .. $cs-1) {
        die "Overlapping table span\n" if defined $grid[$r+$dr][$c+$dc];
        $grid[$r+$dr][$c+$dc] = (!$dr && !$dc) ? $value : '';
      } }
      $c += $cs; $width = $c if $c > $width;
    }
    $r++;
  }
  return '' unless @grid;
  my @lines = map { my $row=$_; '| ' . join(' | ',map { $row->[$_] // '' } 0..$width-1) . ' |' } @grid;
  splice @lines, 1, 0, '| ' . join(' | ', ('---') x $width) . ' |';
  return join "\n", @lines;
}
1;
