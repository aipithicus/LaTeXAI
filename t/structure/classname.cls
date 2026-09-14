\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{classname}[2026/09/14 classname probe]
\LoadClass{article}
\makeatletter
\newcommand{\showname}{\@classname}
\renewcommand*\subjclass[2][1991]{%
  \@ifundefined{subjclassname@#1}{%
    \ClassWarning{\@classname}{Unknown edition (#1) of ACM
      Subject Classification; using '1991'.}%
  }{}%
}
\makeatother
