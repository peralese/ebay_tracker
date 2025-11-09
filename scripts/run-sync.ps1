param(
  [ValidateSet('offline','csv','sqlite','online')] [string] $Profile = 'offline',
  [string] $CsvPath,
  [string] $Since,
  [switch] $DryRun = $true,
  [string] $SummaryCsv,
  [switch] $Verbose
)

function Set-Env($k, $v) {
  $path = "Env:{0}" -f $k
  if ([string]::IsNullOrEmpty($v)) {
    Remove-Item -Path $path -ErrorAction SilentlyContinue | Out-Null
  } else {
    Set-Item -Path $path -Value $v | Out-Null
  }
}

# Base defaults; .env still loads in Python, these override for this process
switch ($Profile) {
  'offline' {
    Set-Env EBT_DISABLE_AUTH 1
    Set-Env EBT_DISABLE_DELETE 1
    Set-Env EBT_LOCAL_CSV $null
  }
  'csv' {
    if (-not $CsvPath) { throw "Profile 'csv' requires -CsvPath." }
    $resolved = (Resolve-Path $CsvPath).Path
    Set-Env EBT_LOCAL_CSV $resolved
    Set-Env EBT_DISABLE_AUTH 1
    Set-Env EBT_DISABLE_DELETE 1
  }
  'sqlite' {
    Set-Env EBT_LOCAL_CSV $null
    # Optional: point to the view if created for --since
    if (-not $env:EBT_SQLITE_TABLE) { Set-Env EBT_SQLITE_TABLE listings_for_sync }
    Set-Env EBT_DISABLE_AUTH 1
    Set-Env EBT_DISABLE_DELETE 1
  }
  'online' {
    Set-Env EBT_LOCAL_CSV $null
    # Respect deletes only when you explicitly clear it
    if (-not $env:EBT_DISABLE_DELETE) { Set-Env EBT_DISABLE_DELETE 1 }
    # Allow auth by ensuring the disable flag is cleared; creds come from .env
    Set-Env EBT_DISABLE_AUTH $null
  }
}

Write-Host "Profile  : $Profile"
if ($env:EBT_LOCAL_CSV) { Write-Host "Local CSV: $($env:EBT_LOCAL_CSV)" }
if ($env:EBT_SQLITE_TABLE) { Write-Host "SQLite   : table=$($env:EBT_SQLITE_TABLE)" }
$authState = if ($env:EBT_DISABLE_AUTH) { 'disabled' } else { 'enabled' }
$delState  = if ($env:EBT_DISABLE_DELETE) { 'disabled' } else { 'enabled' }
Write-Host "Auth     : $authState"
Write-Host "Deletes  : $delState"

$argsList = @()
if ($DryRun) { $argsList += '--dry-run' }
if ($Since) { $argsList += @('--since', $Since) }
if ($SummaryCsv) { $argsList += @('--summary-csv', $SummaryCsv) }
if ($Verbose) { $argsList += '-v' }

Write-Host "Running: python sync.py $($argsList -join ' ')"
& python sync.py @argsList
exit $LASTEXITCODE
