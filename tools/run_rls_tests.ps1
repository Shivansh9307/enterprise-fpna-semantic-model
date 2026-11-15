<#
Runs tests\dax\stage4_*.dax once per role and user case against the Halcyon FPA model open in Power BI Desktop.
Each case writes tests\results\stage4_01_role_check_<case>.csv. All users are fictional (reserved halcyon.example domain).

    powershell.exe -NoProfile -File tools\run_rls_tests.ps1

The case list here must match RLS_CASES in tools\verify_measures.py, which recomputes the expected numbers with pandas.
#>
$ErrorActionPreference = "Stop"
$cases = @(
    @{ Name = "group_cfo";         Roles = "Group Finance";               User = "cfo@halcyon.example" },
    @{ Name = "entity_cfo";        Roles = "Entity Finance";              User = "cfo@halcyon.example" },
    @{ Name = "entity_controller"; Roles = "Entity Finance";              User = "controller@halcyon.example" },
    @{ Name = "entity_uk";         Roles = "Entity Finance";              User = "uk.fpa@halcyon.example" },
    @{ Name = "entity_us";         Roles = "Entity Finance";              User = "us.fpa@halcyon.example" },
    @{ Name = "entity_de";         Roles = "Entity Finance";              User = "de.fpa@halcyon.example" },
    @{ Name = "entity_in";         Roles = "Entity Finance";              User = "in.fpa@halcyon.example" },
    @{ Name = "entity_unmapped";   Roles = "Entity Finance";              User = "nobody@halcyon.example" },
    @{ Name = "emea_uk";           Roles = "EMEA Finance";                User = "uk.fpa@halcyon.example" },
    @{ Name = "emea_unmapped";     Roles = "EMEA Finance";                User = "nobody@halcyon.example" },
    @{ Name = "entity_emea_us";    Roles = "Entity Finance,EMEA Finance"; User = "us.fpa@halcyon.example" }
)
$runner = Join-Path $PSScriptRoot "run_dax.ps1"
$failed = 0
foreach ($case in $cases) {
    $global:LASTEXITCODE = 0
    & $runner -Filter "stage4_*.dax" -Roles $case.Roles -User $case.User -OutSuffix ("_" + $case.Name)
    if ($LASTEXITCODE -ne 0) { $failed++ }
}
if ($failed -gt 0) { exit 1 }
