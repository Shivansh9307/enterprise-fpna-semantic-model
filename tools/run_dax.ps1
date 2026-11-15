<#
Runs DAX query files against the Halcyon FPA model open in Power BI Desktop and writes each result to a CSV.

Why this exists: on this machine `pbir model -q` cannot reach Desktop's local engine (Store install), so the checks go to the
engine port directly with dscmd.exe, the command-line utility that ships with DAX Studio.

Run with Windows PowerShell (not PowerShell 7), because the Tabular Object Model library used to read the database name
and to request a refresh is a .NET Framework build:

    powershell.exe -NoProfile -File tools\run_dax.ps1 -Filter "stage2_*.dax"
    powershell.exe -NoProfile -File tools\run_dax.ps1 -Filter "stage2_*.dax" -Refresh

-Roles and -User run the queries under row-level security, for example
    -Roles "Entity Finance" -User "de.fpa@halcyon.example" -OutSuffix "_entity_de"
-Roles alone applies the role to your own Windows identity. -User needs -Roles. The local engine rejects EffectiveUserName,
so -User uses the ActAs authentication scheme, the mechanism Desktop uses for "View as > Other user".

-Benchmark times each query instead of exporting its result (dscmd benchmark, cold and warm cache runs), for example
    -QueryDir tests\perf -OutDir tests\perfesults -Benchmark
-Vpax <file> exports the model's size statistics (VertiPaq Analyzer) and runs no queries. The file holds model metadata,
including the local data path, so keep it out of the repository.

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
    [string]$Roles = "",
    [string]$User = "",
    [string]$OutSuffix = "",
    [string]$Vpax = "",
    [switch]$Benchmark,
    [int]$Cold = 3,
    [int]$Warm = 5,
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

if ($Vpax) {
    & $DscmdPath vpax $Vpax -s $server -d $database 2>&1 | ForEach-Object { Write-Host $_ }
    if (-not (Test-Path $Vpax)) { exit 1 }
    exit 0
}
if ($User -and -not $Roles) { throw "-User needs -Roles: without a role no security filter applies." }
$connection = "Data Source=$server;Initial Catalog=$database"
if ($Roles) { $connection += ";Roles=$Roles" }
if ($User) {
    $connection += ";Authentication Scheme=ActAs;Ext Auth Info=`"<Properties><UserName>$User</UserName><BypassAuthorization>true</BypassAuthorization><RestrictCatalog>$database</RestrictCatalog></Properties>`""
}
$connectionArg = $connection.Replace('"', '\"')

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$files = Get-ChildItem $QueryDir -Filter $Filter | Sort-Object Name
if (-not $files) { throw "No query files match $QueryDir\$Filter." }
$failed = 0
foreach ($file in $files) {
    $out = Join-Path $OutDir ($file.BaseName + $OutSuffix + ".csv")
    if (Test-Path $out) { Remove-Item $out -Confirm:$false }
    # Windows PowerShell passes embedded double quotes to native programs unescaped, so escape them here.
    $query = (Get-Content $file.FullName -Raw).Replace('"', '\"')
    if ($Benchmark) { $log = & $DscmdPath benchmark $out -s $server -d $database -f $file.FullName --cold $Cold --warm $Warm 2>&1 }
    else { $log = & $DscmdPath csv $out -c $connectionArg -q $query 2>&1 }
    if (Test-Path $out) { Write-Host "ok      $($file.Name)$(if ($Roles) { " as [$Roles] $User" }) -> $out" }
    else { $failed++; Write-Host "FAILED  $($file.Name)"; $log | ForEach-Object { Write-Host "        $_" } }
}
if ($failed -gt 0) { exit 1 }
