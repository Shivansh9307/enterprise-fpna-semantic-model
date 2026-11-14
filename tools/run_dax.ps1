<#
Runs DAX query files against the Halcyon FPA model open in Power BI Desktop and writes each result to a CSV.

Why this exists: on this machine `pbir model -q` cannot reach Desktop's local engine (Store install), so the checks go to the
engine port directly with dscmd.exe, the command-line utility that ships with DAX Studio.

Run with Windows PowerShell (not PowerShell 7), because the Tabular Object Model library used to read the database name
and to request a refresh is a .NET Framework build:

    powershell.exe -NoProfile -File tools\run_dax.ps1 -Filter "stage2_*.dax"
    powershell.exe -NoProfile -File tools\run_dax.ps1 -Filter "stage2_*.dax" -Refresh

-Refresh asks the engine for a full data refresh first. That leaves Desktop with unsaved changes; nothing is written to the project files.
Needs: Power BI Desktop with Halcyon FPA.pbip open, DAX Studio, and Tabular Editor 2 (for its Microsoft.AnalysisServices.Tabular.dll).
#>
param(
    [string]$QueryDir = "tests\dax",
    [string]$Filter = "*.dax",
    [string]$OutDir = "tests\results",
    [string]$WindowTitle = "Halcyon FPA*",
    [string]$DscmdPath = (Join-Path $env:LOCALAPPDATA "Programs\DAX Studio\dscmd.exe"),
    [string]$TomDir = "",
    [switch]$Refresh
)
$ErrorActionPreference = "Stop"

$desktop = Get-Process PBIDesktop -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like $WindowTitle } | Select-Object -First 1
if (-not $desktop) { throw "No Power BI Desktop window with a title like '$WindowTitle' is open." }
$engine = Get-CimInstance Win32_Process -Filter "Name='msmdsrv.exe'" | Where-Object { $_.ParentProcessId -eq $desktop.Id } | Select-Object -First 1
if (-not $engine) { throw "Desktop (PID $($desktop.Id)) has no Analysis Services engine yet. Wait for the model to load." }
$port = Get-NetTCPConnection -OwningProcess $engine.ProcessId -State Listen | Select-Object -ExpandProperty LocalPort -Unique | Select-Object -First 1
if (-not $port) { throw "Could not find the listening port of the engine (PID $($engine.ProcessId))." }
$server = "localhost:$port"

if (-not $TomDir) {
    $dll = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") -Filter "Microsoft.AnalysisServices.Tabular.dll" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $dll) { throw "Microsoft.AnalysisServices.Tabular.dll not found. Pass -TomDir with the Tabular Editor 2 folder." }
    $TomDir = $dll.DirectoryName
}
Add-Type -Path (Join-Path $TomDir "Microsoft.AnalysisServices.Core.dll")
Add-Type -Path (Join-Path $TomDir "Microsoft.AnalysisServices.Tabular.dll")
$tom = New-Object Microsoft.AnalysisServices.Tabular.Server
$tom.Connect($server)
try {
    $db = $tom.Databases[0]
    $database = $db.Name
    if ($Refresh) {
        Write-Host "Requesting a full refresh on $server ..."
        $db.Model.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Full)
        [void]$db.Model.SaveChanges()
    }
    $notReady = @($db.Model.Tables | ForEach-Object { $_.Partitions } | Where-Object { $_.State -ne "Ready" })
    if ($notReady.Count -gt 0) { throw "$($notReady.Count) partition(s) are not loaded. Refresh in Desktop or rerun with -Refresh." }
}
finally { $tom.Disconnect() }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$files = Get-ChildItem $QueryDir -Filter $Filter | Sort-Object Name
if (-not $files) { throw "No query files match $QueryDir\$Filter." }
$failed = 0
foreach ($file in $files) {
    $out = Join-Path $OutDir ($file.BaseName + ".csv")
    if (Test-Path $out) { Remove-Item $out -Confirm:$false }
    # Windows PowerShell passes embedded double quotes to native programs unescaped, so escape them here.
    $query = (Get-Content $file.FullName -Raw).Replace('"', '\"')
    $log = & $DscmdPath csv $out -s $server -d $database -q $query 2>&1
    if (Test-Path $out) { Write-Host "ok      $($file.Name) -> $out" }
    else { $failed++; Write-Host "FAILED  $($file.Name)"; $log | ForEach-Object { Write-Host "        $_" } }
}
if ($failed -gt 0) { exit 1 }
