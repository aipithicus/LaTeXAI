% gmvenue.cls -- synthetic venue class for the gauntlet-master fixture.
% Bracketed tags name inventory cases; coverage.md maps each tag to its use.
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{gmvenue}[2026/10/27 v0.1 gauntlet-master venue class]
\newif\ifgm@numeric          % [D10] option flags: one set by an option ...
\newif\ifgm@final
\let\ifgm@draft\iffalse      % [D11] ... one hand-made with \let\ifX\iffalse
\DeclareOption{numericcites}{\gm@numerictrue}
\DeclareOption{final}{\gm@finaltrue}
\DeclareOption{draft}{\let\ifgm@draft\iftrue}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ExecuteOptions{final}
\ProcessOptions\relax
\LoadClass{article}[2020/01/01]% [C2] local class over \LoadClass, trailing date

% [P8] package choice inside a live option flag
\ifgm@numeric
  \RequirePackage[numbers,sort&compress]{natbib}
  \def\gm@bst{unsrtnat}
\else
  \RequirePackage[authoryear,round]{natbib}
  \def\gm@bst{plainnat}% [B6] the style is chosen by a class flag
\fi

% [D1] format probes in a class
\ifx\pdfoutput\undefined
  \def\gm@engine{no \string\pdfoutput}
\else
  \ifx\pdfoutput\relax \def\gm@engine{relaxed}\else \def\gm@engine{pdfoutput}\fi
\fi
\ifdefined\XeTeXversion \def\gm@unicode{xetex}\else \def\gm@unicode{8bit}\fi
\IfFileExists{gmlogo.pdf}{\def\gm@logo{logo}}{\def\gm@logo{no logo}}% [D5] absent file

% [T12] expl3 code between \ExplSyntaxOn and \ExplSyntaxOff
\ExplSyntaxOn
\seq_new:N \g__gm_authors_seq
\cs_new_protected:Npn \gm_add_author:n #1
  { \seq_gput_right:Nn \g__gm_authors_seq {#1} }
\NewDocumentCommand \gmauthor { m } { \gm_add_author:n {#1} }
\NewDocumentCommand \gmauthorlist { }
  { \seq_use:Nnnn \g__gm_authors_seq { ~and~ } { ,~ } { ,~and~ } }
\ExplSyntaxOff

% [T10] \makeatletter run inside a macro, before the arguments are read:
% the caller's arguments are tokenized with @ as a letter (svjour3 pattern).
\newcommand{\gmcolumncase}{\makeatletter\gm@twocoltest}
\newcommand{\gm@twocoltest}[2]{%
  \if@twocolumn\def\@gtempa{#2}\else\def\@gtempa{#1}\fi\@gtempa\makeatother}
\def\gm@one{one-column text}
\def\gm@two{two-column text}
\endinput
