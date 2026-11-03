# Invocado por la tarea programada de Windows (ver scripts/setup_task_scheduler.ps1).
# Corre el pipeline completo y agrega la salida a un log diario en logs/.
#
# La redirección se hace vía cmd.exe (>> 2>&1) a propósito: en Windows PowerShell 5.1,
# redirigir stderr de un ejecutable nativo con *>> envuelve cada línea en un
# NativeCommandError y corrompe el archivo. cmd.exe no tiene ese problema.
Set-Location -Path (Join-Path $PSScriptRoot "..")

if (-not (Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

$logFile = "logs\scheduler_{0:yyyy-MM-dd}.log" -f (Get-Date)
$pythonExe = Join-Path (Get-Location) ".venv\Scripts\python.exe"

$env:PYTHONIOENCODING = "utf-8"  # evita '?' en tildes al redirigir stdout a archivo en Windows
cmd /c "`"$pythonExe`" -m scheduler.run >> `"$logFile`" 2>&1"
