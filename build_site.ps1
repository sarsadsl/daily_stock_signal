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
        "pullback_pb_v6_trend_review_variants.json"
    )) {
        Copy-FileIfExists -Source (Join-Path $reportsSource $name) -Destination (Join-Path $reportsTarget $name)
    }

    foreach ($name in @(
        "pullback_experiment_summary.html",
        "pullback_pb_v4_0_1y_discount2_swing.html",
        "pullback_pb_v5_0_strong_filter_holdout.html",
        "pullback_pb_v6_trend_review_variants.html",
        "pullback_pb_v6_trend_review_variants.md"
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
