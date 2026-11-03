# Genera el ejecutable de Windows (dist\EVEStationTradingAnalyzer.exe).
# Uso: powershell -ExecutionPolicy Bypass -File build.ps1

python -m pip install -r requirements.txt -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "Tests fallidos: build cancelado."; exit $LASTEXITCODE }

python -m PyInstaller --noconfirm --onefile --windowed `
    --name "EVEStationTradingAnalyzer" `
    --add-data "config;config" `
    main.py

Write-Host "Ejecutable generado en dist\EVEStationTradingAnalyzer.exe"
