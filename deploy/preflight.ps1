param(
    [string]$EnvFile = "$PSScriptRoot\.env.preprod",
    [switch]$Live,
    [switch]$SkipPorts
)

$arguments = @("$PSScriptRoot\preflight.py", "--env-file", $EnvFile)
if ($Live) { $arguments += "--live" }
if ($SkipPorts) { $arguments += "--skip-ports" }
python @arguments
exit $LASTEXITCODE

