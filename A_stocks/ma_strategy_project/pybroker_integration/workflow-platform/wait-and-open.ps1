param(
  [string]$Url = 'http://127.0.0.1:5173/',
  [int]$TimeoutSec = 90
)

$deadline = (Get-Date).AddSeconds($TimeoutSec)
$ok = $false

while ((Get-Date) -lt $deadline) {
  try {
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
    if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
      $ok = $true
      break
    }
  } catch {
    Start-Sleep -Milliseconds 500
  }
}

if ($ok) {
  Start-Process $Url
} else {
  Write-Host "[WARN] Server not ready within ${TimeoutSec}s. Open manually: $Url"
}
