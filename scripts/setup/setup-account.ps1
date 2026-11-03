$ErrorActionPreference = 'Stop'
$pythonCommand = if ($env:WASM_AGENT_PYTHON) { $env:WASM_AGENT_PYTHON } else { 'python' }
$forwarded = @($args | ForEach-Object {
    if ($_ -in @('-WhatIf', '--what-if', '--dry-run')) { '--dry-run' } else { $_ }
})
& $pythonCommand (Join-Path $PSScriptRoot 'setup_account.py') @forwarded
exit $LASTEXITCODE
