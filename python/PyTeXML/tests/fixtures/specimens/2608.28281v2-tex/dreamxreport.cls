% DreamX technical report / paper class.
% Extracted from the DreamX-World 1.0 report layout and generalized for reuse.
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{dreamxreport}[2026/07/30 v1.2 DreamX-World report template]

\newif\ifdreamx@numericcitations
\dreamx@numericcitationsfalse
\DeclareOption{numbers}{\dreamx@numericcitationstrue}
\DeclareOption{authoryear}{\dreamx@numericcitationsfalse}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax
\LoadClass{article}
\if@twocolumn
  \ClassError{dreamxreport}
    {The twocolumn option is not supported}
    {This template uses a breakable full-width title card. Use the default
     single-column layout or adapt the title stage explicitly.}
\fi

% Page and typography.
\RequirePackage[
  top=2.25cm,
  bottom=2.5cm,
  left=2.5cm,
  right=2.5cm,
  columnsep=0.65cm
]{geometry}
\RequirePackage[T1]{fontenc}
\RequirePackage{lmodern}
\renewcommand*\ttdefault{cmvtt}
\RequirePackage[english]{babel}
\RequirePackage{microtype}
\RequirePackage{setspace}
\RequirePackage{parskip}
\RequirePackage{etoolbox}
\emergencystretch=2em

% Figures, floats, and title-card rendering.
\RequirePackage{graphicx}
\RequirePackage{subcaption}
\RequirePackage{float}
\RequirePackage{xcolor}
\RequirePackage{colortbl}
\RequirePackage{tikz}

% Tables and structured lists used by the report.
\RequirePackage{array}
\RequirePackage{booktabs}
\RequirePackage{tabularx}

% References.
\RequirePackage{amsmath}
\RequirePackage{amssymb}
\RequirePackage{amsthm}
\RequirePackage{mathtools}
\RequirePackage{hyperref}
\ifdreamx@numericcitations
  \RequirePackage[numbers,sort&compress]{natbib}
\else
  \RequirePackage[round,authoryear]{natbib}
\fi

% Headings, captions, and page furniture.
\RequirePackage{caption}
\RequirePackage{fancyhdr}
\providecommand{\FloatBarrier}{}

% Semantic DreamX colors. config/brand.tex is the intended override point.
\definecolor{dreamxprimary}{HTML}{0091FF}
\definecolor{dreamxtext}{HTML}{1C2B33}
\definecolor{dreamxbackground}{HTML}{EAF4FB}
\definecolor{dreamxpurple}{HTML}{7366CC}
\definecolor{dreamxcyan}{HTML}{00B4E5}
\definecolor{dreamxlightgray}{HTML}{F5F5F5}
\definecolor{dreamxtablerowalt}{HTML}{EAF4FB}
\definecolor{dreamxheadergray}{HTML}{888888}
\colorlet{amapblue}{dreamxprimary}
\colorlet{amapfg}{dreamxtext}
\colorlet{amapbg}{dreamxbackground}
\colorlet{BrandPurple}{dreamxpurple}
\colorlet{BrandCyan}{dreamxcyan}
\colorlet{LightGray}{dreamxlightgray}
\colorlet{TableRowAlt}{dreamxtablerowalt}
\colorlet{HeaderGray}{dreamxheadergray}

\hypersetup{
  colorlinks,
  linkcolor=dreamxprimary,
  citecolor=dreamxprimary,
  urlcolor=dreamxprimary
}
\def\bibfont{\small}

\renewcommand\section{\@startsection{section}{1}{\z@}%
  {-3.5ex \@plus -1ex \@minus -.2ex}%
  {2.3ex \@plus .2ex}%
  {\Large\sffamily\bfseries\color{dreamxprimary}}}
\renewcommand\subsection{\@startsection{subsection}{2}{\z@}%
  {-3.25ex\@plus -1ex \@minus -.2ex}%
  {1.5ex \@plus .2ex}%
  {\large\sffamily\bfseries\color{dreamxprimary}}}
\renewcommand\subsubsection{\@startsection{subsubsection}{3}{\z@}%
  {-3.25ex\@plus -1ex \@minus -.2ex}%
  {1.5ex \@plus .2ex}%
  {\normalsize\sffamily\bfseries\color{dreamxprimary}}}
\renewcommand\paragraph{\@startsection{paragraph}{4}{\z@}%
  {3.25ex \@plus1ex \@minus.2ex}%
  {-1em}%
  {\itshape}}
\DeclareTextFontCommand{\textbf}{\bfseries\sffamily}

\DeclareCaptionLabelSeparator{dreamx}{}
\DeclareCaptionFormat{dreamx}{{\sffamily\textbf{#1 #2}} #3}
\captionsetup{
  singlelinecheck=false,
  format=dreamx,
  labelsep=dreamx,
  font=small
}
\captionsetup[sub]{
  singlelinecheck=true,
  format=dreamx,
  labelsep=dreamx,
  font=small
}

% Public brand and header configuration.
\newcommand{\dreamx@logo}{assets/dreamx-logo.png}
\newcommand{\dreamx@runningtitle}{DreamX Report}
\newcommand{\dreamx@headerleft}{DreamX Team}
\newcommand{\dreamx@headerright}{\today}
\newcommand{\DreamXLogo}[1]{\gdef\dreamx@logo{#1}}
\newcommand{\DreamXRunningTitle}[1]{\gdef\dreamx@runningtitle{#1}}
\newcommand{\DreamXHeaderLeft}[1]{\gdef\dreamx@headerleft{#1}}
\newcommand{\DreamXHeaderRight}[1]{\gdef\dreamx@headerright{#1}}
\newcommand{\DreamXPDFAuthor}[1]{\hypersetup{pdfauthor={#1}}}

% Title-card data.
\newcommand{\dreamx@title}{}
\newcommand{\dreamx@authorlist}{}
\newif\ifdreamx@authorlinebreak
\dreamx@authorlinebreakfalse
\newcommand{\dreamx@affiliationlist}{}
\newif\ifdreamx@affiliationlinebreak
\dreamx@affiliationlinebreakfalse
\newcommand{\dreamx@contributionlist}{}
\newcommand{\dreamx@authorplacement}{title}
\newcommand{\dreamx@titlebyline}{}
\newcommand{\dreamx@authorsectiontitle}{Authors}
\newcommand{\dreamx@authorsectionlabel}{Team Members}
\newcommand{\dreamx@authorsectionnote}{}
\newcommand{\dreamx@authoracknowledgements}{}
\newcommand{\dreamx@metadatalist}{}
\newcommand{\dreamx@abstract}{}
\newif\ifdreamx@authorsectionprinted
\dreamx@authorsectionprintedfalse
\newif\ifdreamx@acknowledgementsprinted
\dreamx@acknowledgementsprintedfalse

\newcommand{\DreamXAuthorPlacement}[1]{%
  \ifstrequal{#1}{title}
    {\gdef\dreamx@authorplacement{title}}
    {%
      \ifstrequal{#1}{end}
        {\gdef\dreamx@authorplacement{end}}
        {%
          \ClassError{dreamxreport}
            {Unknown author placement `#1'}
            {Use \string\DreamXAuthorPlacement{title} or
             \string\DreamXAuthorPlacement{end}.}%
        }%
    }%
}
\newcommand{\DreamXTitleByline}[1]{\gdef\dreamx@titlebyline{#1}}
\newcommand{\DreamXAuthorSectionTitle}[1]{\gdef\dreamx@authorsectiontitle{#1}}
\newcommand{\DreamXAuthorSectionLabel}[1]{\gdef\dreamx@authorsectionlabel{#1}}
\newcommand{\DreamXAuthorSectionNote}[1]{\gdef\dreamx@authorsectionnote{#1}}

\renewcommand{\title}[1]{%
  \gdef\dreamx@title{#1}%
  \hypersetup{pdftitle={#1}}%
}

\newcommand{\dreamx@authorformat}[2][]{{\small\sffamily\bfseries #2$^{#1}$}}
\ExplSyntaxOn
\seq_new:N \g_dreamx_end_authors_seq
\cs_new_protected:Npn \dreamx_end_author_add:nn #1#2
  {
    \seq_gput_right:Nn \g_dreamx_end_authors_seq
      { \dreamx_end_author_format:nn {#1} {#2} }
  }
\cs_new:Npn \dreamx_end_author_format:nn #1#2
  {
    #2
    \tl_if_blank:nF {#1} { ${}^{#1}$ }
  }
\cs_new:Npn \dreamx_end_author_print:
  {
    \seq_use:Nnnn \g_dreamx_end_authors_seq
      { ~and~ }
      { ,~ }
      { ,~and~ }
  }
\cs_new_eq:NN \dreamx@endauthoradd \dreamx_end_author_add:nn
\cs_new_eq:NN \dreamx@endauthornames \dreamx_end_author_print:
\ExplSyntaxOff
\renewcommand{\author}[2][]{%
  \ifdefempty{\dreamx@authorlist}
    {\gappto\dreamx@authorlist{\dreamx@authorformat[#1]{#2}}}
    {%
      \ifdreamx@authorlinebreak
        \gappto\dreamx@authorlist{\dreamx@authorformat[#1]{#2}}%
        \global\dreamx@authorlinebreakfalse
      \else
        \gappto\dreamx@authorlist{, \dreamx@authorformat[#1]{#2}}%
      \fi
    }%
  \dreamx@endauthoradd{#1}{#2}%
}

\newcommand{\DreamXAuthorLineBreak}{%
  \ifdefempty{\dreamx@authorlist}{}{%
    \gappto\dreamx@authorlist{\\[0.08cm]}%
    \global\dreamx@authorlinebreaktrue
  }%
}

\newcommand{\dreamx@affiliationformat}[2][]{{\footnotesize $^{#1}$#2}}
\newcommand{\affiliation}[2][]{%
  \ifdefempty{\dreamx@affiliationlist}
    {\gappto\dreamx@affiliationlist{\dreamx@affiliationformat[#1]{#2}}}
    {%
      \ifdreamx@affiliationlinebreak
        \gappto\dreamx@affiliationlist{\dreamx@affiliationformat[#1]{#2}}%
        \global\dreamx@affiliationlinebreakfalse
      \else
        \gappto\dreamx@affiliationlist{, \dreamx@affiliationformat[#1]{#2}}%
      \fi
    }%
}

\newcommand{\DreamXAffiliationLineBreak}{%
  \ifdefempty{\dreamx@affiliationlist}{}{%
    \gappto\dreamx@affiliationlist{\\[0.04cm]}%
    \global\dreamx@affiliationlinebreaktrue
  }%
}

\newcommand{\dreamx@contributionformat}[2][]{{\footnotesize $^{#1}$#2}}
\newcommand{\contribution}[2][]{%
  \ifdefempty{\dreamx@contributionlist}
    {\gappto\dreamx@contributionlist{\dreamx@contributionformat[#1]{#2}}}
    {\gappto\dreamx@contributionlist{, \dreamx@contributionformat[#1]{#2}}}%
}

\newcommand{\dreamx@endaffiliations}{%
  \begingroup
  \renewcommand{\dreamx@affiliationformat}[2][]{%
    {\small\ifstrempty{##1}{}{${}^{##1}$}##2}%
  }%
  \dreamx@affiliationlist
  \endgroup
}

\newcommand{\dreamx@endcontributions}{%
  \begingroup
  \renewcommand{\dreamx@contributionformat}[2][]{%
    {\small\ifstrempty{##1}{}{${}^{##1}$}##2}%
  }%
  \dreamx@contributionlist
  \endgroup
}

\newcommand{\DreamXPrintAuthorSection}{%
  \ifdefstring{\dreamx@authorplacement}{end}
    {%
      \ifdreamx@authorsectionprinted
        \ClassWarningNoLine{dreamxreport}{Author section already printed}%
      \else
        \dreamx@authorsectionprintedtrue
        \ifdefempty{\dreamx@authorlist}
          {%
            \ifdefempty{\dreamx@authoracknowledgements}
              {%
                \ClassWarningNoLine{dreamxreport}{%
                  No authors configured; the end author section was omitted}%
              }
              {%
                \section*{Acknowledgements}
                \dreamx@authoracknowledgements\par
                \global\dreamx@acknowledgementsprintedtrue
              }%
          }
          {%
            \FloatBarrier
            \section*{\dreamx@authorsectiontitle}
            \ifdefempty{\dreamx@authorsectionlabel}
              {}
              {\paragraph{\dreamx@authorsectionlabel.}}
            \ifdefempty{\dreamx@authorsectionnote}
              {}
              {\emph{\dreamx@authorsectionnote}\par}
            \dreamx@endauthornames.\par
            \ifdefempty{\dreamx@affiliationlist}
              {}
              {\medskip\dreamx@endaffiliations\par}
            \ifdefempty{\dreamx@contributionlist}
              {}
              {\smallskip\dreamx@endcontributions\par}
            \ifdefempty{\dreamx@authoracknowledgements}
              {}
              {%
                \paragraph{Acknowledgements.}
                \dreamx@authoracknowledgements\par
                \global\dreamx@acknowledgementsprintedtrue
              }%
          }%
      \fi
    }
    {}%
}

\AtEndDocument{%
  \ifdefstring{\dreamx@authorplacement}{end}
    {%
      \ifdreamx@authorsectionprinted
      \else
        \ClassWarningNoLine{dreamxreport}{%
          Author placement is `end', but
          \string\DreamXPrintAuthorSection\space was not called}%
      \fi
    }
    {}%
}

\newcommand{\dreamx@metadataformat}[2][]{{\small{\sffamily\bfseries #1:} #2}}
\newcommand{\metadata}[2][]{%
  \ifdefempty{\dreamx@metadatalist}
    {\gappto\dreamx@metadatalist{\dreamx@metadataformat[#1]{#2}}}
    {\gappto\dreamx@metadatalist{\par\dreamx@metadataformat[#1]{#2}}}%
}

\newcommand{\reportabstract}[1]{\gdef\dreamx@abstract{#1}}
\newcommand{\email}[1]{\href{mailto:#1}{\nolinkurl{#1}}}
\newcommand{\correspondence}[1]{\metadata[Correspondence]{#1}}
\renewcommand{\date}[1]{\metadata[Date]{#1}}
\newcommand{\DreamXAuthorAcknowledgements}[1]{%
  \gdef\dreamx@authoracknowledgements{#1}%
}
\newcommand{\DreamXPrintAcknowledgements}{%
  \ifdefstring{\dreamx@authorplacement}{end}
    {}
    {%
      \ifdefempty{\dreamx@authoracknowledgements}
        {}
        {%
          \ifdreamx@acknowledgementsprinted
            \ClassWarningNoLine{dreamxreport}{Acknowledgements already printed}%
          \else
            \FloatBarrier
            \section*{Acknowledgements}
            \dreamx@authoracknowledgements\par
            \global\dreamx@acknowledgementsprintedtrue
          \fi
        }%
    }%
}

% Reusable DreamX callout components.  These use only core LaTeX primitives so
% the report remains portable to minimal TeX installations.
\newenvironment{dreamxportablebox}[2]
  {\par\medskip\noindent\begin{minipage}{\linewidth}%
   \color{#1}\hrule height 0.8pt\smallskip
   \color{dreamxtext}\ifstrempty{#2}{}{\textbf{#2}\par\smallskip}}
  {\smallskip\color{dreamxprimary}\hrule height 0.8pt
   \end{minipage}\par\medskip}

\newenvironment{templatebox}[1]
  {\begin{dreamxportablebox}{gray!80!black}{#1}}
  {\end{dreamxportablebox}}

\newenvironment{highlight}
  {\begin{dreamxportablebox}{dreamxcyan}{}}
  {\end{dreamxportablebox}}

\newenvironment{maincontributions}[1][Our main contributions are:]
  {%
    \begin{highlight}
    \textbf{#1}
    \begin{itemize}
    \setlength{\itemsep}{1pt}
    \setlength{\topsep}{2pt}
  }
  {%
    \end{itemize}
    \end{highlight}
  }

\newenvironment{keyfinding}[1][Key Finding]
  {\begin{dreamxportablebox}{dreamxpurple}{#1}}
  {\end{dreamxportablebox}}

\newenvironment{tipbox}[1]
  {\begin{dreamxportablebox}{dreamxprimary}{#1}}
  {\end{dreamxportablebox}}

% DreamX-World table primitives. Captions remain above the tabular material.
\newcommand{\DreamXTableHeaderRow}{\rowcolor{dreamxprimary}}
\newcommand{\DreamXTableAltRow}{\rowcolor{dreamxtablerowalt}}
\newcommand{\DreamXTableHead}[1]{\textcolor{white}{\textbf{#1}}}
\newcommand{\DreamXCompactTableSetup}{%
  \renewcommand{\arraystretch}{1.2}%
  \scriptsize
  \setlength{\tabcolsep}{2pt}%
}
\newcommand{\DreamXResultTableSetup}{%
  \renewcommand{\arraystretch}{1.2}%
  \footnotesize
  \setlength{\tabcolsep}{2.8pt}%
}
\newcommand{\DreamXTableNote}[1]{%
  \par\vspace{2pt}%
  {\scriptsize #1\par}%
}

\newcommand{\figplaceholder}[2]{%
  \fcolorbox{dreamxprimary!40}{dreamxlightgray}{%
    \parbox{0.95\linewidth}{%
      \vspace{2.5cm}
      \centering
      {\large\color{dreamxprimary}\textbf{#1}}\\[0.5em]
      {\color{dreamxtext}#2}
      \vspace{2cm}
    }%
  }%
}

% Page styles.
\setlength{\headheight}{12pt}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\footnotesize\color{dreamxheadergray}\sffamily\dreamx@runningtitle}
\fancyhead[R]{\footnotesize\color{dreamxheadergray}\thepage}
\fancyfoot[C]{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}

\fancypagestyle{dreamxfirstpage}{
  \fancyhf{}
  \fancyhead[L]{\small\sffamily\color{dreamxprimary}\dreamx@headerleft}
  \fancyhead[R]{\small\color{dreamxheadergray}\dreamx@headerright}
  \fancyfoot[C]{\footnotesize\color{gray}\thepage}
  \renewcommand{\headrulewidth}{0.4pt}
  \renewcommand{\footrulewidth}{0pt}
  \renewcommand{\headrule}{%
    \vspace{2pt}%
    \color{dreamxheadergray}%
    \hrule width\headwidth height 0.4pt}
}

% Float rhythm.
\setlength{\textfloatsep}{11pt plus 2pt minus 3pt}
\setlength{\floatsep}{10pt plus 2pt minus 2pt}
\setlength{\intextsep}{10pt plus 2pt minus 2pt}
\renewcommand{\topfraction}{0.9}
\renewcommand{\bottomfraction}{0.8}
\renewcommand{\textfraction}{0.08}
\renewcommand{\floatpagefraction}{0.72}
\setlength{\@fptop}{0pt}
\setlength{\@fpsep}{12pt plus 2pt minus 2pt}
\setlength{\@fpbot}{0pt plus 1fil}

\newcommand{\dreamx@logonode}{%
  \ifdefempty{\dreamx@logo}{}{%
    \IfFileExists{\dreamx@logo}{%
      \node[
        anchor=north east,
        at=(frame.north east),
        xshift=-0.2cm,
        yshift=0.55cm,
        inner sep=0pt
      ]{%
        \begin{tikzpicture}
          \clip (0,0) rectangle (2.2cm,2.2cm);
          \node[anchor=south west,inner sep=0pt] at (0,0)
            {\includegraphics[width=2cm]{\dreamx@logo}};
        \end{tikzpicture}%
      };%
    }{%
      \ClassWarning{dreamxreport}{Logo `\dreamx@logo' not found; continuing without it}%
    }%
  }%
}

\newlength{\dreamx@titlewidth}
\newlength{\dreamx@cardwidth}

\newcommand{\dreamx@maketitlebox}{%
  \ifdefempty{\dreamx@title}
    {\ClassWarning{dreamxreport}{No title configured}}
    {}%
  \setlength{\dreamx@cardwidth}{\dimexpr\linewidth-1cm\relax}%
  \noindent\begin{tikzpicture}
  \node[
    name=frame,
    anchor=north west,
    inner sep=0.5cm,
    rounded corners=10pt,
    fill=dreamxbackground,
    text width=\dreamx@cardwidth
  ] at (0,0) {\begin{minipage}{\dreamx@cardwidth}
    \setlength{\parindent}{0cm}
    \setlength{\parskip}{0.5cm}
    {%
      \setlength{\parskip}{0cm}
      \raggedright
      \hyphenpenalty=10000\relax
      \exhyphenpenalty=10000\relax
      {%
        \setstretch{1.618}
        \setlength{\dreamx@titlewidth}{\linewidth}
        \ifdefempty{\dreamx@logo}{}{\addtolength{\dreamx@titlewidth}{-2.2cm}}
        \begin{minipage}{\dreamx@titlewidth}
          \raggedright
          {\huge\sffamily\bfseries\dreamx@title}
        \end{minipage}\par
      }%
      \vskip 0.35cm
      \ifdefstring{\dreamx@authorplacement}{title}
        {%
          \ifdefempty{\dreamx@authorlist}
            {%
              \ifdefempty{\dreamx@affiliationlist}
                {%
                  \ifdefempty{\dreamx@contributionlist}
                    {}
                    {%
                      \dreamx@contributionlist\par
                      \vskip 0.2cm
                    }%
                }
                {%
                  \dreamx@affiliationlist\par
                  \dreamx@contributionlist\par
                  \vskip 0.2cm
                }%
            }
            {%
              \dreamx@authorlist\par
              \vskip 0.2cm
              \dreamx@affiliationlist\par
              \dreamx@contributionlist\par
            }%
        }
        {%
          \ifdefempty{\dreamx@titlebyline}
            {}
            {%
              {\sffamily\bfseries\dreamx@titlebyline}\par
              \vskip 0.2cm
            }%
        }%
    }%
    {\color{dreamxtext}\dreamx@abstract}\par
    \vskip 0.5cm
    {%
      \setlength{\parskip}{0cm}
      \ifdefempty{\dreamx@metadatalist}
        {\vspace*{0.65cm}}
        {\dreamx@metadatalist\par}
    }%
  \end{minipage}};
  \dreamx@logonode
  \end{tikzpicture}\par
  \FloatBarrier
}

\renewcommand{\maketitle}{%
  \thispagestyle{dreamxfirstpage}
  \dreamx@maketitlebox
}

\newcommand{\reportappendix}{%
  \appendix
  {\huge\sffamily\bfseries Appendix\par}
}
\newcommand{\beginappendix}{\reportappendix}
