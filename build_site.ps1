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

    foreach ($entry in $latestByCode.Values) {
        Copy-Item -LiteralPath $entry.File.FullName -Destination (Join-Path $targetDir $entry.File.Name) -Force
    }
}

$dashboardSource = Join-Path $rootPath "signal_dashboard.html"
$dashboardTarget = Join-Path $sitePath "index.html"
Copy-FileIfExists -Source $dashboardSource -Destination $dashboardTarget

$reportsSource = Join-Path $rootPath "reports"
if (Test-Path -LiteralPath $reportsSource) {
    $reportsTarget = Join-Path $sitePath "reports"
    New-Item -ItemType Directory -Path $reportsTarget -Force | Out-Null
    foreach ($name in @("daily_signal_alert.json", "daily_signal_alert.csv", "daily_signal_alert.txt")) {
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

$metadata = [ordered]@{
    built_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    source = "GitHub Actions"
}
$metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $sitePath "build.json") -Encoding UTF8

Write-Host "Built static site at $sitePath"
