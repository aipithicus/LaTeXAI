# /=====================================================================\ #
# |  LaTeXML::Core::Parameters                                          | #
# | Representation of Parameters for Control Sequences                  | #
# |=====================================================================| #
# | Part of LaTeXML:                                                    | #
# |  Public domain software, produced as part of work done by the       | #
# |  United States Government & not subject to copyright in the US.     | #
# |---------------------------------------------------------------------| #
# | Bruce Miller <bruce.miller@nist.gov>                        #_#     | #
# | http://dlmf.nist.gov/LaTeXML/                              (o o)    | #
# \=========================================================ooo==U==ooo=/ #
package LaTeXML::Core::Parameters;
use strict;
use warnings;
use LaTeXML::Global;
use LaTeXML::Common::Object;
use LaTeXML::Common::Error;
use LaTeXML::Core::Parameter;
use LaTeXML::Core::Tokens;
use base qw(LaTeXML::Common::Object);

sub new {
  my ($class, @paramspecs) = @_;
  return bless [@paramspecs], $class; }

sub getParameters {
  my ($self) = @_;
  return @$self; }

sub stringify {
  my ($self) = @_;
  my $string = '';
  foreach my $parameter (@$self) {
    my $s = $parameter->stringify;
    $string .= ' ' if ($string =~ /\w$/) && ($s =~ /^\w/);
    $string .= $s; }
  return $string; }

sub equals {
  my ($self, $other) = @_;
  return (defined $other)
    && ((ref $self) eq (ref $other)) && ($self->stringify eq $other->stringify); }

sub getNumArgs {
  my ($self) = @_;
  my $n = 0;
  foreach my $parameter (@$self) {
    $n++ unless $$parameter{novalue}; }
  return $n; }

our $REVERT_DROPS = 0;

sub revertArguments {
  my ($self, @args) = @_;
  my @tokens = ();
  foreach my $parameter (@$self) {
    next if $$parameter{novalue};
    my $arg = shift(@args);
    # Keep Tokens that carry per-token occurrences as a unit so Invocation
    # and Tokens() can replay them. Flattening through Revert would drop the
    # fieldhash. Extents always come from the parameter's own reverter;
    # occurrences ride only when that output is the argument tokens, or
    # those tokens wrapped by one leading and one trailing delimiter.
    if ($arg && (ref $arg eq 'LaTeXML::Core::Tokens') && $arg->hasCaptureOccurrences) {
      my @rev  = $parameter->revert($arg);
      my $wrap = _occurrence_reversion_wrap($arg, \@rev);
      if ($wrap && $wrap eq 'bare') {
        push(@tokens, $arg); }
      elsif ($wrap && $wrap eq 'wrap') {
        push(@tokens, $rev[0], $arg, $rev[-1]); }
      else {
        $REVERT_DROPS++;
        push(@tokens, @rev); } }
    else {
      push(@tokens, $parameter->revert($arg)); } }
  return @tokens; }

# Identity of the argument's own Token objects, not equals(): the wrapper
# tokens (T_BEGIN/T_END constants, or a fresh T_OTHER('[') from Optional)
# are recognized only as the extra leading/trailing pair.
sub _occurrence_reversion_wrap {
  my ($arg, $rev) = @_;
  my @arg = @$arg;
  my @rev = @$rev;
  return 'bare' if @rev == @arg && _same_token_identity(\@rev, \@arg);
  return 'wrap' if @rev == (@arg + 2) && @rev >= 2
    && _same_token_identity([@rev[1 .. $#rev - 1]], \@arg);
  return; }

sub _same_token_identity {
  my ($a, $b) = @_;
  return 0 unless @$a == @$b;
  for my $i (0 .. $#$a) {
    return 0 unless defined $a->[$i] && defined $b->[$i] && $a->[$i] == $b->[$i]; }
  return 1; }

sub readArguments {
  no warnings 'recursion';
  my ($self, $gullet, $fordefn) = @_;
  my @args = ();
  my ($p, $v);
  return map { $p = $_; $v = $p && $p->read($gullet, $fordefn); ($$p{novalue} ? () : $v); } @$self; }

sub readArgumentsAndDigest {
  no warnings 'recursion';
  my ($self, $stomach, $fordefn) = @_;
  my @args   = ();
  my $gullet = $stomach->getGullet;
  foreach my $parameter (@$self) {
    my $value = $parameter->read($gullet, $fordefn);
    if (!$$parameter{novalue}) {
      $value = $parameter->digest($stomach, $value, $fordefn);
      push(@args, $value); } }
  return @args; }

sub reparseArgument {
  my ($self, $gullet, $tokens) = @_;
  if (defined $tokens) {
    return $gullet->readingFromMouth($tokens, sub {
        no warnings 'recursion';
        $self->readArguments($gullet); }); }
  else {
    return (); } }

END {
  print STDERR "LATEXAI_REVERT_DROPS=$REVERT_DROPS\n"
    if $ENV{LATEXAI_COUNT_REVERT_DROPS}; }

#======================================================================
1;

__END__

=pod

=head1 NAME

C<LaTeXML::Core::Parameters> - formal parameters.

=head1 DESCRIPTION

Provides a representation for the formal parameters of L<LaTeXML::Core::Definition>s:
It extends L<LaTeXML::Common::Object>.

=head2 METHODS

=over 4

=item C<< @parameters = $parameters->getParameters; >>

Return the list of C<LaTeXML::Core::Parameter> contained in C<$parameters>.

=item C<< @tokens = $parameters->revertArguments(@args); >>

Return a list of L<LaTeXML::Core::Token> that would represent the arguments
such that they can be parsed by the Gullet.

=item C<< @args = $parameters->readArguments($gullet,$fordefn); >>

Read the arguments according to this C<$parameters> from the C<$gullet>.
This takes into account any special forms of arguments, such as optional,
delimited, etc.

=item C<< @args = $parameters->readArgumentsAndDigest($stomach,$fordefn); >>

Reads and digests the arguments according to this C<$parameters>, in sequence.
this method is used by Constructors.

=back

=head1 SEE ALSO

L<LaTeXML::Core::Parameter>.

=head1 AUTHOR

Bruce Miller <bruce.miller@nist.gov>

=head1 COPYRIGHT

Public domain software, produced as part of work done by the
United States Government & not subject to copyright in the US.

=cut
