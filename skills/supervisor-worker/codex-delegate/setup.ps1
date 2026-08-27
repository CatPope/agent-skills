# Bootstrap check for codex-delegate (Windows / PowerShell). Idempotent; installs nothing.
# codex_task.py uses the Python standard library only, so there are no deps to install.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = if ($env:CODEX_DELEGATE_PY) { $env:CODEX_DELEGATE_PY } else { "python" }
& $py -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"
if ($LASTEXITCODE -ne 0) { throw "[codex-delegate] need Python >= 3.9" }
& $py -m py_compile scripts/codex_task.py

if (Get-Command codex -ErrorAction SilentlyContinue) {
    Write-Host "[codex-delegate] codex CLI: $((Get-Command codex).Source)"
} else {
    Write-Host "[codex-delegate] WARNING: codex CLI not on PATH - the helper will fall back to a known install path."
}
Write-Host "[codex-delegate] ready."
