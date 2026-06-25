param(
    [string]$Root = $PSScriptRoot,
    [string]$Output = "site"
)

$ErrorActionPreference = "Stop"

$rootPath = (Resolve-Path -LiteralPath $Root).Path
$sitePath = Join-Path $rootPath $Output

if (Test-Path -LiteralPath $sitePath) {
    Remove-Item -LiteralPath $sitePath -Recurse -Force
}

New-Item -ItemType Directory -Path $sitePath | Out-Null

$script:stockManifest = @()

function Copy-FileIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (Test-Path -LiteralPath $Source) {
        $parent = Split-Path -Parent $Destination
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
}

function Copy-LatestStockCsvs {
    param(
        [Parameter(Mandatory = $true)][string]$Market
    )

    $sourceDir = Join-Path (Join-Path $rootPath "data") "all_$Market"
    if (-not (Test-Path -LiteralPath $sourceDir)) {
        return
    }

    $targetDir = Join-Path (Join-Path $sitePath "data") "all_$Market"
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

    Copy-FileIfExists `
        -Source (Join-Path $sourceDir "_symbols.csv") `
        -Destination (Join-Path $targetDir "_symbols.csv")

    $latestByCode = @{}
    Get-ChildItem -LiteralPath $sourceDir -Filter "*.csv" -File |
        Where-Object { -not $_.Name.StartsWith("_") } |
        ForEach-Object {
            $match = [regex]::Match($_.Name, "^(\d{4})_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$")
            if (-not $match.Success) {
                return
            }

            $code = $match.Groups[1].Value
            $endDate = $match.Groups[3].Value
            $current = $latestByCode[$code]
            if (-not $current -or $endDate -gt $current.EndDate -or ($endDate -eq $current.EndDate -and $_.LastWriteTimeUtc -gt $current.File.LastWriteTimeUtc)) {
                $latestByCode[$code] = [pscustomobject]@{
                    EndDate = $endDate
                    File = $_
                }
            }
        }

    foreach ($code in ($latestByCode.Keys | Sort-Object)) {
        $entry = $latestByCode[$code]
        Copy-Item -LiteralPath $entry.File.FullName -Destination (Join-Path $targetDir $entry.File.Name) -Force
        $match = [regex]::Match($entry.File.Name, "^(\d{4})_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$")
        $script:stockManifest += [ordered]@{
            key = ("{0}:{1}" -f $Market.ToUpperInvariant(), $code)
            market = $Market.ToUpperInvariant()
            stock_no = $code
            file = ("../data/all_{0}/{1}" -f $Market, $entry.File.Name)
            start_date = $match.Groups[2].Value
            end_date = $match.Groups[3].Value
        }
    }
}

$dashboardSource = Join-Path $rootPath "signal_dashboard.html"
$dashboardTarget = Join-Path $sitePath "index.html"
Copy-FileIfExists -Source $dashboardSource -Destination $dashboardTarget

$rankingsSource = Join-Path $rootPath "top_signal_rankings.html"
$rankingsTarget = Join-Path $sitePath "rankings.html"
Copy-FileIfExists -Source $rankingsSource -Destination $rankingsTarget

$mwpSource = Join-Path $rootPath "mwp_a_strategy.html"
$mwpTarget = Join-Path $sitePath "mwp_a_strategy.html"
Copy-FileIfExists -Source $mwpSource -Destination $mwpTarget

$mwpRealizedSource = Join-Path $rootPath "mwp_a_realized_pnl.html"
$mwpRealizedTarget = Join-Path $sitePath "mwp_a_realized_pnl.html"
Copy-FileIfExists -Source $mwpRealizedSource -Destination $mwpRealizedTarget

$reportsSource = Join-Path $rootPath "reports"
if (Test-Path -LiteralPath $reportsSource) {
    $reportsTarget = Join-Path $sitePath "reports"
    New-Item -ItemType Directory -Path $reportsTarget -Force | Out-Null
    foreach ($name in @(
        "daily_signal_alert.json",
        "daily_signal_alert.csv",
        "daily_signal_alert.txt",
        "daily_signal_top_lists.json",
        "recent_all_signal_backtest_smart.json",
        "pullback_pb_v4_0_1y_discount2_swing.json",
        "pullback_pb_v6_trend_review_variants.json",
        "pullback_pb_v6e_holdout.json",
        "pullback_standard_unit_rerun.json",
        "pullback_pb_v19_main_wave_addon.json",
        "pullback_pb_v20_fuzzy_addon.json",
        "pullback_pb_v21_addon_stop_variants.json",
        "pullback_pb_v22_structural_addon_stop.json",
        "pullback_pb_v23_independent_lifecycle.json",
        "pullback_plus_independent_versions.json",
        "pullback_plus_random_splits.json",
        "pullback_pb_v18_finite_capital.json",
        "pullback_pb_v18_unlimited.json",
        "pullback_v9_v18_addon_compare.json",
        "pullback_v18_score_pool_tests.json",
        "pullback_v18_all_scores_no_limit.json",
        "pullback_v18_all_scores_addon.json",
        "pullback_v18_deploy_compare.json",
        "pullback_v9_fixed_random_splits.json",
        "pullback_v9_fixed_addon_random_splits.json",
        "mwp_addon_strategy_comparison.json",
        "mwp_addon_unit_cap_experiment.json",
        "mwp_technical_filter_experiment.json",
        "mwp_c_return_first_capped.json",
        "mwp_a_strategy_tracking.json"
    )) {
        Copy-FileIfExists -Source (Join-Path $reportsSource $name) -Destination (Join-Path $reportsTarget $name)
    }

    foreach ($name in @(
        "pullback_experiment_summary.html",
        "pullback_pb_v4_0_1y_discount2_swing.html",
        "pullback_pb_v5_0_strong_filter_holdout.html",
        "pullback_pb_v6_trend_review_variants.html",
        "pullback_pb_v6_trend_review_variants.md",
        "pullback_pb_v6e_holdout.html",
        "pullback_pb_v6e_holdout.md",
        "pullback_standard_unit_rerun.html",
        "pullback_pb_v19_main_wave_addon.html",
        "pullback_pb_v20_fuzzy_addon.html",
        "pullback_pb_v21_addon_stop_variants.html",
        "pullback_pb_v22_structural_addon_stop.html",
        "pullback_pb_v23_independent_lifecycle.html",
        "pullback_plus_independent_versions.html",
        "pullback_plus_random_splits.html",
        "pullback_pb_v18_unlimited.html",
        "pullback_pb_v18_unlimited.md",
        "pullback_v9_v18_addon_compare.html",
        "pullback_v9_v18_addon_compare.md",
        "pullback_v18_score_pool_tests.html",
        "pullback_v18_score_pool_tests.md",
        "pullback_v18_all_scores_no_limit.html",
        "pullback_v18_all_scores_no_limit.md",
        "pullback_v18_all_scores_addon.html",
        "pullback_v18_all_scores_addon.md",
        "pullback_v18_deploy_compare.html",
        "pullback_v18_deploy_compare.md",
        "pullback_v9_fixed_random_splits.html",
        "pullback_v9_fixed_random_splits.md",
        "pullback_v9_fixed_addon_random_splits.html",
        "pullback_v9_fixed_addon_random_splits.md",
        "mwp_addon_strategy_comparison.html",
        "mwp_addon_strategy_comparison.md",
        "mwp_addon_unit_cap_experiment.html",
        "mwp_addon_unit_cap_experiment.md",
        "mwp_technical_filter_experiment.html",
        "mwp_technical_filter_experiment.md",
        "mwp_c_return_first_capped.html",
        "mwp_c_return_first_capped.md"
    )) {
        Copy-FileIfExists -Source (Join-Path $reportsSource $name) -Destination (Join-Path $reportsTarget $name)
    }
}

$chartsSource = Join-Path (Join-Path $rootPath "charts") "daily_alert"
if (Test-Path -LiteralPath $chartsSource) {
    $chartsTarget = Join-Path (Join-Path $sitePath "charts") "daily_alert"
    New-Item -ItemType Directory -Path $chartsTarget -Force | Out-Null
    Copy-Item -Path (Join-Path $chartsSource "*") -Destination $chartsTarget -Force -ErrorAction SilentlyContinue
}

Copy-LatestStockCsvs -Market "twse"
Copy-LatestStockCsvs -Market "tpex"

$reportsOutput = Join-Path $sitePath "reports"
New-Item -ItemType Directory -Path $reportsOutput -Force | Out-Null
$script:stockManifest |
    Sort-Object market, stock_no |
    ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath (Join-Path $reportsOutput "stock_data_manifest.json") -Encoding UTF8

$metadata = [ordered]@{
    built_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    source = "GitHub Actions"
}
$metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $sitePath "build.json") -Encoding UTF8

Write-Host "Built static site at $sitePath"
