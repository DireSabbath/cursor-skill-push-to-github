# Prepend Git and GitHub CLI to PATH for this process.
# This machine often has git/gh installed but missing from the agent PATH.

$candidates = @(
    'C:\Program Files\Git\cmd',
    'C:\Program Files\Git\bin',
    "$env:LOCALAPPDATA\portable-dev-tools\gh\bin",
    'C:\Program Files\GitHub CLI',
    "$env:LOCALAPPDATA\GitHub CLI"
)

foreach ($dir in $candidates) {
    if ($dir -and (Test-Path -LiteralPath $dir)) {
        $env:Path = "$dir;$env:Path"
    }
}

function Resolve-Tool([string]$Name, [string[]]$FallbackPaths) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in $FallbackPaths) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

$GitExe = Resolve-Tool 'git' @(
    'C:\Program Files\Git\cmd\git.exe',
    'C:\Program Files\Git\bin\git.exe'
)
$GhExe = Resolve-Tool 'gh' @(
    "$env:LOCALAPPDATA\portable-dev-tools\gh\bin\gh.exe",
    'C:\Program Files\GitHub CLI\gh.exe'
)

if (-not $GitExe) { throw 'git not found. Install Git for Windows.' }
if (-not $GhExe) { throw 'gh not found. Install GitHub CLI or restore portable-dev-tools\gh.' }

Write-Output "GIT=$GitExe"
Write-Output "GH=$GhExe"
