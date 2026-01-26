param(
  [string]$BaseUrl = 'http://127.0.0.1:8000',
  [string]$Token,
  [int]$NumScreens = 1000,
  [int]$DurationSec = 60,
  [int]$PollMin = 5,
  [int]$PollMax = 15
)

if (-not $Token) {
  Write-Error 'Token is required: pass -Token <display_token>'
  exit 2
}

$env:BASE_URL = $BaseUrl
$env:TOKEN = $Token
$env:NUM_SCREENS = "$NumScreens"
$env:DURATION_SEC = "$DurationSec"
$env:POLL_MIN = "$PollMin"
$env:POLL_MAX = "$PollMax"

Write-Host "Running load test against $env:BASE_URL for $env:NUM_SCREENS screens..."

$py = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (Test-Path $py) {
  & $py "$PSScriptRoot\simulate_screens_load.py"
} else {
  & python "$PSScriptRoot\simulate_screens_load.py"
}
