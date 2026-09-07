@echo off
if "%PERL_ROOT%"=="" (
  echo fetch-ctan kpsewhich: PERL_ROOT is not set 1>&2
  exit /b 1
)
"%PERL_ROOT%\perl\bin\perl.exe" "%~dp0kpsewhich.pl" %*
