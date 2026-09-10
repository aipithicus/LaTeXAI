#requires -Version 7.5
# Qualification double: exits successfully without writing TAP evidence.
param(
    [string] $Driver,
    [string] $ResultPath,
    [string] $TapPath,
    [string] $StdOutPath,
    [string] $StdErrPath,
    [string] $CheckoutRoot,
    [string] $PerlPath,
    [string] $TapRunScript,
    [string] $LibDirectory
)
exit 0
