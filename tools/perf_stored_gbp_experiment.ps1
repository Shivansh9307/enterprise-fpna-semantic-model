<#
Performance experiment: currency conversion in DAX (what the model does) against a stored GBP column (the alternative).

Adds a temporary calculated column 'GL'[Amount GBP Temp] to the model open in Power BI Desktop, benchmarks the queries in
tests\perf\experiment (dscmd benchmark, cold and warm cache), reads the column's size, then removes the column again.
The change lives only in Desktop's memory: nothing is written to the project files, and the column is removed even if a step fails.

    powershell.exe -NoProfile -File tools\perf_stored_gbp_experiment.ps1

Run with Windows PowerShell (not PowerShell 7). Needs the same tools as tools\run_dax.ps1. Synthetic data.
#>
param(
    [string]$WindowTitle = "Halcyon FPA*",
    [string]$DscmdPath = (Join-Path $env:LOCALAPPDATA "Programs\DAX Studio\dscmd.exe"),
    [string]$OutDir = "tests\perf\results",
    [int]$Cold = 5,
    [int]$Warm = 5
)
$ErrorActionPreference = "Stop"
$columnName = "Amount GBP Temp"
$expression = "'GL'[Amount Local] * LOOKUPVALUE ( 'FX Rates'[Avg Rate To GBP], 'FX Rates'[Period Date], 'GL'[Period Date], 'FX Rates'[Currency Code], 'GL'[Currency Code] )"

$desktop = Get-Process PBIDesktop -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like $WindowTitle } | Select-Object -First 1
if (-not $desktop) { throw "No Power BI Desktop window with a title like '$WindowTitle' is open." }
$engine = Get-CimInstance Win32_Process -Filter "Name='msmdsrv.exe'" | Where-Object { $_.ParentProcessId -eq $desktop.Id } | Select-Object -First 1
$port = Get-NetTCPConnection -OwningProcess $engine.ProcessId -State Listen | Select-Object -ExpandProperty LocalPort -Unique | Select-Object -First 1
$server = "localhost:$port"
$dll = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") -Filter "Microsoft.AnalysisServices.Tabular.dll" -Recurse | Select-Object -First 1
Add-Type -Path (Join-Path $dll.DirectoryName "Microsoft.AnalysisServices.Core.dll")
Add-Type -Path $dll.FullName

$tom = New-Object Microsoft.AnalysisServices.Tabular.Server
$tom.Connect($server)
try {
    $db = $tom.Databases[0]
    $gl = $db.Model.Tables["GL"]
    if ($gl.Columns.ContainsName($columnName)) { $gl.Columns.Remove($gl.Columns[$columnName]); [void]$db.Model.SaveChanges() }
    $column = New-Object Microsoft.AnalysisServices.Tabular.CalculatedColumn
    $column.Name = $columnName
    $column.Expression = $expression
    $column.IsHidden = $true
    $column.IsAvailableInMDX = $false
    $gl.Columns.Add($column)
    [void]$db.Model.SaveChanges()
    $gl.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Calculate)
    [void]$db.Model.SaveChanges()
    Write-Host "Added temporary column 'GL'[$columnName] (data type $($gl.Columns[$columnName].DataType))."
    try {
        New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
        foreach ($file in Get-ChildItem "tests\perf\experiment" -Filter "*.dax" | Sort-Object Name) {
            $out = Join-Path $OutDir ($file.BaseName + ".csv")
            if (Test-Path $out) { Remove-Item $out -Confirm:$false }
            $log = & $DscmdPath benchmark $out -s $server -d $db.Name -f $file.FullName --cold $Cold --warm $Warm 2>&1
            if (Test-Path $out) { Write-Host "ok      $($file.Name) -> $out" } else { Write-Host "FAILED  $($file.Name)"; $log | ForEach-Object { Write-Host "        $_" } }
        }
        # column sizes from the engine's storage view, written next to the timings
        $sizeQuery = "SELECT DIMENSION_NAME, COLUMN_ID, USED_SIZE FROM `$SYSTEM.DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS WHERE DIMENSION_NAME = 'GL'"
        $sizeOut = Join-Path $OutDir "experiment_gl_column_segments.csv"
        if (Test-Path $sizeOut) { Remove-Item $sizeOut -Confirm:$false }
        [void](& $DscmdPath csv $sizeOut -s $server -d $db.Name -q $sizeQuery 2>&1)
        if (Test-Path $sizeOut) { Write-Host "ok      column segment sizes -> $sizeOut" } else { Write-Host "FAILED  column segment sizes" }
    }
    finally {
        $gl.Columns.Remove($gl.Columns[$columnName])
        [void]$db.Model.SaveChanges()
        Write-Host "Removed temporary column 'GL'[$columnName]."
    }
}
finally { $tom.Disconnect() }
