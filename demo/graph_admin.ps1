[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][guid]$TenantId,
    [Parameter(Mandatory = $true)][string]$RequestPath,
    [Parameter(Mandatory = $true)][string]$ResponsePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$status = $null

try {
    $request = Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json
    $method = [string]$request.method
    $path = [string]$request.path
    if ($method -notin @("GET", "POST", "PATCH", "DELETE") -or
        -not $path.StartsWith("/") -or $path.StartsWith("//")) {
        throw [ArgumentException]::new("Invalid administrator request.")
    }
    $uri = [uri]("https://graph.microsoft.com/v1.0" + $path)
    if ($uri.Host -ne "graph.microsoft.com" -or $uri.Scheme -ne "https" -or $uri.Fragment -or
        $uri.AbsolutePath -notmatch "^/v1\.0/(applications|servicePrincipals|me)(/|$)" -or
        ($uri.AbsolutePath -eq "/v1.0/me" -and $method -ne "GET") -or
        $uri.AbsolutePath -match "(?i)addPassword|passwordCredentials|/secrets") {
        throw [UnauthorizedAccessException]::new("Request is outside the administrator Graph scope.")
    }
    $bodyProperty = $request.PSObject.Properties["body"]
    $body = if ($null -ne $bodyProperty) { $bodyProperty.Value } else { $null }
    if ($null -ne $body -and ($body | ConvertTo-Json -Depth 50 -Compress) -match '"passwordCredentials"\s*:') {
        throw [UnauthorizedAccessException]::new("Password credentials are not used by the demo.")
    }
    Import-Module Microsoft.Graph.Authentication -MinimumVersion 2.41.2 -ErrorAction Stop
    Connect-MgGraph -TenantId $TenantId.ToString() -ContextScope CurrentUser -NoWelcome -Scopes @(
        "AgentIdentityBlueprint.ReadWrite.All", "AgentIdentityBlueprintPrincipal.ReadWrite.All",
        "AgentIdentity.ReadWrite.All", "Application.ReadWrite.All", "AppRoleAssignment.ReadWrite.All", "User.Read"
    ) -ErrorAction Stop
    $context = Get-MgContext
    if ([guid]$context.TenantId -ne $TenantId -or $context.AuthType -ne "Delegated" -or
        "Directory.AccessAsUser.All" -in $context.Scopes) {
        throw [UnauthorizedAccessException]::new("A dedicated delegated administrator session is required.")
    }
    $parameters = @{
        Method = $method; Uri = $uri.AbsoluteUri; OutputType = "HttpResponseMessage"; ErrorAction = "Stop"
        SkipHttpErrorCheck = $true
        Headers = @{ "OData-Version" = "4.0" }
    }
    if ($null -ne $body) {
        $parameters.Body = $body | ConvertTo-Json -Depth 50 -Compress
        $parameters.ContentType = "application/json"
    }
    $response = Invoke-MgGraphRequest @parameters
    try {
        $status = [int]$response.StatusCode
        if ($status -lt 200 -or $status -ge 300) {
            throw [IO.IOException]::new("Administrator Graph request failed.")
        }
        $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $data = if ($text) { $text | ConvertFrom-Json -Depth 50 } else { $null }
        if ($status -ne 204 -and $null -eq $data) {
            throw [IO.InvalidDataException]::new("Missing administrator Graph response.")
        }
    } finally {
        $response.Dispose()
    }
    $result = @{ success = $true; status_code = $status; data = $data }
} catch {
    $result = @{
        success = $false; status_code = $status; error_type = $_.Exception.GetType().FullName
        error_id = $_.FullyQualifiedErrorId
    }
}
[IO.File]::WriteAllText(
    [IO.Path]::GetFullPath($ResponsePath), ($result | ConvertTo-Json -Depth 60 -Compress),
    [Text.UTF8Encoding]::new($false)
)
if (-not $result.success) { exit 2 }
