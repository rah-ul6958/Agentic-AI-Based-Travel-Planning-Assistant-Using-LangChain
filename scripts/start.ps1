$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path (Get-Location) "venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython -m streamlit run app.py
} else {
    python -m streamlit run app.py
}
