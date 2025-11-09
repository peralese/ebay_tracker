param(
  [ValidateSet('sqlite','csv','offline','online')] [string] $Profile = 'sqlite',
  [string] $CsvPath
)

function Set-Env($k, $v) {
  $path = "Env:{0}" -f $k
  if ([string]::IsNullOrEmpty($v)) {
    Remove-Item -Path $path -ErrorAction SilentlyContinue | Out-Null
  } else {
    Set-Item -Path $path -Value $v | Out-Null
  }
}

switch ($Profile) {
  'sqlite' {
    Set-Env EBT_LOCAL_CSV $null
    if (-not $env:EBT_SQLITE_TABLE) { Set-Env EBT_SQLITE_TABLE listings }
  }
  'csv' {
    if (-not $CsvPath) { throw "Profile 'csv' requires -CsvPath." }
    $resolved = (Resolve-Path $CsvPath).Path
    Set-Env EBT_LOCAL_CSV $resolved
  }
  'offline' {
    Set-Env EBT_DISABLE_AUTH 1
    Set-Env EBT_DISABLE_DELETE 1
  }
  'online' {
    Set-Env EBT_DISABLE_AUTH $null
  }
}

Write-Host "Profile  : $Profile"
if ($env:EBT_LOCAL_CSV) { Write-Host "Local CSV: $($env:EBT_LOCAL_CSV)" }
if ($env:EBT_SQLITE_TABLE) { Write-Host "SQLite   : table=$($env:EBT_SQLITE_TABLE)" }
$authState = if ($env:EBT_DISABLE_AUTH) { 'disabled' } else { 'enabled' }
Write-Host "Auth     : $authState"

Write-Host "Running: streamlit run ebay_tracker_app.py"
& streamlit run ebay_tracker_app.py
exit $LASTEXITCODE
