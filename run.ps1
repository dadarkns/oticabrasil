$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pythonLauncher) {
    & $pythonLauncher.Source -3 (Join-Path $project 'server.py')
    exit $LASTEXITCODE
}
$python3 = Get-Command python3 -ErrorAction SilentlyContinue
if ($python3) {
    & $python3.Source (Join-Path $project 'server.py')
    exit $LASTEXITCODE
}
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python -and $python.Source -notlike '*WindowsApps*') {
    & $python.Source (Join-Path $project 'server.py')
    exit $LASTEXITCODE
}
throw 'Python 3.10+ não foi encontrado. Instale Python ou use Docker Compose.'
