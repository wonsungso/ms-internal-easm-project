[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][guid]$TenantId,
    [Parameter(Mandatory = $true)][ValidateSet("PowerPlatform", "Purview")][string]$Service,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [datetimeoffset]$StartTime = [datetimeoffset]::UtcNow.AddDays(-7),
    [datetimeoffset]$EndTime = [datetimeoffset]::UtcNow,
    [ValidateRange(1, 200)][int]$MaxPages = 40
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$output = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $output) { throw "Existing export must not be overwritten." }
if ($StartTime -gt $EndTime -or ($EndTime - $StartTime).TotalDays -gt 30) {
    throw "Activity Explorer requires an ordered window of at most 30 days."
}

$reads = [Collections.Generic.List[object]]::new()
$verified = $false
$version = "not_installed"

function Read-Property($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) { return $property.Value }
    return $null
}

function Error-Reason($Record) {
    if ($Record.CategoryInfo.Category -eq "PermissionDenied") { return "permission_denied" }
    $response = Read-Property $Record.Exception "Response"
    $status = Read-Property $response "StatusCode"
    if ($null -ne $status) {
        if ([int]$status -in @(401, 403)) { return "permission_denied" }
        if ([int]$status -in @(404, 405, 501)) { return "feature_unavailable" }
    }
    if ($Record.Exception -is [Management.Automation.CommandNotFoundException]) { return "feature_unavailable" }
    return "error"
}

function Failed-Read([string]$Source, [string]$Command, [string]$Reason, [string]$Detail) {
    $reads.Add([ordered]@{
        source = $Source; command = $Command; module_version = $version
        scope = "separate administrator read; unavailable or incomplete"
        completed = $false; object_count = $null; reason = $Reason; detail = $Detail
        observed_at = [datetimeoffset]::UtcNow.ToString("o")
    })
}

function Invoke-Read([scriptblock]$Operation) {
    for ($attempt = 0; $attempt -lt 4; $attempt++) {
        try { return & $Operation } catch {
            $response = Read-Property $_.Exception "Response"
            $status = Read-Property $response "StatusCode"
            if ($null -eq $status -or [int]$status -notin @(429, 500, 502, 503, 504) -or $attempt -eq 3) {
                throw
            }
            Write-Warning "Transient read failure; retrying the same official read command."
            Start-Sleep -Seconds ([math]::Pow(2, $attempt))
        }
    }
}

if ($Service -eq "PowerPlatform") {
    $ready = $false
    try {
        Import-Module Microsoft.PowerApps.Administration.PowerShell -MinimumVersion 2.0.220 -ErrorAction Stop
        $version = (Get-Module Microsoft.PowerApps.Administration.PowerShell).Version.ToString()
        $ready = $true
    } catch {
        foreach ($pair in @(
            @("powerplatform.environment_roles", "Get-AdminPowerAppEnvironmentRoleAssignment"),
            @("powerplatform.dlp_policies", "Get-AdminDlpPolicy")
        )) {
            Failed-Read $pair[0] $pair[1] "feature_unavailable" ("Official module unavailable: " + $_.Exception.GetType().Name)
        }
    }
    if ($ready) {
        try {
            Add-PowerAppsAccount -Endpoint prod -TenantID $TenantId.ToString() -ErrorAction Stop | Out-Null
            $verified = $true
        } catch {
            foreach ($pair in @(
                @("powerplatform.environment_roles", "Get-AdminPowerAppEnvironmentRoleAssignment"),
                @("powerplatform.dlp_policies", "Get-AdminDlpPolicy")
            )) {
                Failed-Read $pair[0] $pair[1] (Error-Reason $_) ("Administrator login failed: " + $_.Exception.GetType().Name)
            }
        }
        if ($verified) {
            foreach ($pair in @(
                @("powerplatform.environment_roles", "Get-AdminPowerAppEnvironmentRoleAssignment"),
                @("powerplatform.dlp_policies", "Get-AdminDlpPolicy")
            )) {
                try {
                    $command = $pair[1]
                    $rows = @(Invoke-Read { & $command -ErrorAction Stop })
                    $scope = if ($pair[0] -eq "powerplatform.environment_roles") {
                        "administrator-visible non-Dataverse environment role assignments; not unique Maker users"
                    } else { "DLP policy objects returned by the official tenant administrator cmdlet" }
                    $reads.Add([ordered]@{
                        source = $pair[0]; command = $command; module_version = $version
                        scope = $scope; completed = $true; object_count = $rows.Count
                        observed_at = [datetimeoffset]::UtcNow.ToString("o")
                        detail = "Object count only; connector classifications, group members and policy effectiveness not inferred. No people or policy content exported."
                    })
                } catch {
                    Failed-Read $pair[0] $pair[1] (Error-Reason $_) ("Official read failed: " + $_.Exception.GetType().Name)
                }
            }
        }
    }
} else {
    $ready = $false
    try {
        Import-Module ExchangeOnlineManagement -MinimumVersion 3.9.0 -ErrorAction Stop
        $version = (Get-Module ExchangeOnlineManagement).Version.ToString()
        $ready = $true
    } catch {
        Failed-Read "purview.activity_explorer" "Export-ActivityExplorerData" "feature_unavailable" ("Official module unavailable: " + $_.Exception.GetType().Name)
    }
    if ($ready) {
        try {
            Connect-IPPSSession -ShowBanner:$false -ErrorAction Stop | Out-Null
            $connections = @(Get-ConnectionInformation | Where-Object { $_.IsEopSession -and $_.State -eq "Connected" })
            if ($connections.Count -ne 1 -or [guid]$connections[0].TenantID -ne $TenantId) {
                throw [UnauthorizedAccessException]::new("Compliance session tenant mismatch or ambiguity.")
            }
            $verified = $true
        } catch {
            Failed-Read "purview.activity_explorer" "Export-ActivityExplorerData" (Error-Reason $_) ("Compliance login/tenant verification failed: " + $_.Exception.GetType().Name)
        }
        if ($verified) {
            try {
                $counts = @{ AIAppInteraction = 0; CopilotInteraction = 0; DLPRuleMatch = 0; DLPRuleEnforce = 0; unclassified = 0 }
                $count = 0
                $cookie = $null
                $seen = [Collections.Generic.HashSet[string]]::new()
                $finished = $false
                for ($page = 0; $page -lt $MaxPages; $page++) {
                    $parameters = @{
                        StartTime = $StartTime.UtcDateTime; EndTime = $EndTime.UtcDateTime
                        OutputFormat = "Json"; PageSize = 5000; ErrorAction = "Stop"
                        Filter1 = @("Activity", "AIAppInteraction", "CopilotInteraction", "DLPRuleMatch", "DLPRuleEnforce")
                    }
                    if ($null -ne $cookie) { $parameters.PageCookie = $cookie }
                    $result = Invoke-Read { Export-ActivityExplorerData @parameters }
                    $last = Read-Property $result "LastPage"
                    $json = Read-Property $result "ResultData"
                    if ($last -isnot [bool] -or $json -isnot [string]) {
                        throw [IO.InvalidDataException]::new("Activity Explorer page shape is invalid.")
                    }
                    $records = @(ConvertFrom-Json -InputObject $json -ErrorAction Stop)
                    foreach ($record in $records) {
                        $count++
                        $activity = Read-Property $record "Activity"
                        if ($activity -is [string] -and $counts.ContainsKey($activity)) { $counts[$activity]++ }
                        else { $counts.unclassified++ }
                        $sensitive = Read-Property $record "SensitiveInfoTypeCount"
                        $number = 0
                        if ($null -ne $sensitive -and [int]::TryParse([string]$sensitive, [ref]$number) -and $number -ge 0) {
                            if (-not $counts.ContainsKey("sensitive_type_observed")) { $counts.sensitive_type_observed = 0 }
                            if ($number -gt 0) { $counts.sensitive_type_observed++ }
                        }
                        $label = Read-Property $record "SensitivityLabel"
                        if ($label -is [string]) {
                            if (-not $counts.ContainsKey("sensitivity_label_observed")) { $counts.sensitivity_label_observed = 0 }
                            if ($label) { $counts.sensitivity_label_observed++ }
                        }
                    }
                    if ($last) { $finished = $true; break }
                    $cookie = Read-Property $result "WaterMark"
                    if ($cookie -isnot [string] -or -not $cookie -or -not $seen.Add($cookie)) {
                        throw [IO.InvalidDataException]::new("Activity Explorer continuation is missing or repeated.")
                    }
                }
                if (-not $finished) { throw [IO.InvalidDataException]::new("Activity Explorer paging limit reached.") }
                $reads.Add([ordered]@{
                    source = "purview.activity_explorer"; command = "Export-ActivityExplorerData"
                    module_version = $version; scope = "tenant AI interaction and DLP activity aggregates; no Agent attribution or leak verdict"
                    completed = $true; object_count = $count; counts = $counts
                    observed_at = [datetimeoffset]::UtcNow.ToString("o")
                    window_start = $StartTime.ToUniversalTime().ToString("o"); window_end = $EndTime.ToUniversalTime().ToString("o")
                    detail = "Completed official Activity Explorer pages. No prompts, responses, people, file paths, sensitive values or continuation cookies exported. Access does not mean leakage."
                })
            } catch {
                Failed-Read "purview.activity_explorer" "Export-ActivityExplorerData" (Error-Reason $_) ("Read incomplete or failed: " + $_.Exception.GetType().Name)
            }
        }
    }
}

$packet = [ordered]@{
    schema_version = 1; source_type = "official_admin_read"; tenant_id = $TenantId.ToString()
    tenant_verified = $verified; exported_at = [datetimeoffset]::UtcNow.ToString("o"); reads = @($reads.ToArray())
}
$parent = [IO.Path]::GetDirectoryName($output)
[void][IO.Directory]::CreateDirectory($parent)
[IO.File]::WriteAllText($output, ($packet | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
Write-Output ("Administrator read export saved: " + $output)
if (@($reads | Where-Object { -not $_.completed }).Count -gt 0) { exit 2 }
exit 0
