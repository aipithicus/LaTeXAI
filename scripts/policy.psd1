@{
    PowerShellMinimumVersion = '7.5'
    ScriptIdentity = @(
        'scripts/profile.ps1'
        'scripts/latexai-common.ps1'
        'scripts/latexai-aliases.ps1'
        'scripts/gauntlet-run.ps1'
        'scripts/gauntlet-select.ps1'
        'scripts/gauntlet-worker.ps1'
        'scripts/markdown-compare.ps1'
        'scripts/kpsewhich.cmd'
        'scripts/test-run.ps1'
        'scripts/test-jobs.ps1'
        'scripts/test-worker.ps1'
        'scripts/policy.psd1'
        'scripts/preloads/gauntlet.sty.ltxml'
        'scripts/preloads/lxprofile.sty.ltxml'
        'tools/dev/kpsewhich.pl'
        'tools/dev/tap-run.pl'
        'tools/dev/generate.pl'
    )
    Direct = @{
        TimeoutSeconds = 300
        CleanupTimeoutSeconds = 15
        WaitSliceMilliseconds = 50
    }
    Markdown = @{
        TimeoutSeconds = 900
        CleanupTimeoutSeconds = 15
        WaitSliceMilliseconds = 20
        SamplePeakWorkingSet = $true
    }
    Gauntlet = @{
        MaxWorkers = 10
        ReservedCores = 2
        ProcessTimeoutSeconds = 3600
        WaitTimeoutSeconds = 28800
        ExecutionTimeoutSeconds = 28800
        NativeTimeoutSeconds = 3600
        CleanupTimeoutSeconds = 30
        SearchPath = @('scripts/preloads')
        Preload = @('gauntlet.sty')
        ConversionWorkingDirectory = 'source'
    }
    Test = @{
        Budgets = @{
            ProcessTimeoutSeconds = 900
            WaitTimeoutSeconds = 7200
            ExecutionTimeoutSeconds = 7200
            CleanupTimeoutSeconds = 30
            ReservedCores = 2
            MinItemsPerWorker = 1
        }
        Selections = @{
            math = @('t/40_math.t', 't/70_parse.t')
            capture = @('t/45_capture.t', 't/99_capture_audit.t')
            bindings = @('t/8*.t')
        }
        DefaultEstimatedCost = 10
        EstimatedCost = @{
            't/99_capture_audit.t' = 125
            't/45_capture.t' = 117
            't/50_structure.t' = 91
            't/53_alignment.t' = 79
            't/22_fonts.t' = 67
            't/10_expansion.t' = 65
            't/70_parse.t' = 63
            't/65_graphics.t' = 62
            't/80_complex.t' = 51
            't/857_tikz-cd.t' = 46
            't/40_math.t' = 40
            't/878_tikz.t' = 40
            't/879_forest.t' = 40
        }
        ExtraWrites = @{
            't/02_kpsewhich.t' = @('temp/t/kpsewhich')
            't/003_unit_imagemagick.t' = @('t/unit/triangle.png')
            't/931_epub.t' = @('931_test.log')
        }
    }
}
