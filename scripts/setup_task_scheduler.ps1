# Registra (o reemplaza) las DOS tareas programadas de Windows del proyecto:
#   - EveMarketScreener_Pipeline:  motor de mercado (scheduler/run.py), cada 4 horas.
#   - EveMarketScreener_Positions: motor de posiciones (scheduler/orders_run.py), cada
#     5 minutos — revisa tus órdenes activas contra el libro de órdenes real y notifica
#     por Telegram solo cuando cambia tu posición (mismo componente de notificación que
#     usa el motor de mercado para oportunidades nuevas).
# Ambas corren solo mientras el usuario tenga sesión iniciada (no se guarda contraseña
# ni se usa una cuenta de servicio). MultipleInstances=IgnoreNew evita corridas
# superpuestas si una ejecución anterior sigue activa.
#
# Ambas se lanzan vía run_hidden.vbs (wscript.exe) en vez de powershell.exe directo:
# -WindowStyle Hidden no alcanza cuando el Programador de Tareas dispara powershell.exe
# directamente, igual flashea una consola — con la tarea de posiciones corriendo cada
# 5 min, eso se nota todo el tiempo. El wrapper VBS evita el flash por completo.
#
# Ejecutar una vez, manualmente, desde una terminal normal.

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd

$hiddenLauncher = Join-Path $PSScriptRoot "run_hidden.vbs"

# --- Motor de mercado: cada 4 horas ---
$marketTaskName = "EveMarketScreener_Pipeline"
$marketScript = Join-Path $PSScriptRoot "run_scheduled.ps1"
$marketAction = New-ScheduledTaskAction -Execute "wscript.exe" `
    -Argument "`"$hiddenLauncher`" `"$marketScript`""
$marketTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 4) -RepetitionDuration (New-TimeSpan -Days 3650)

Register-ScheduledTask -TaskName $marketTaskName -Action $marketAction -Trigger $marketTrigger `
    -Settings $settings -Force | Out-Null

# --- Motor de posiciones: cada 5 minutos ---
$positionsTaskName = "EveMarketScreener_Positions"
$positionsScript = Join-Path $PSScriptRoot "run_scheduled_orders.ps1"
$positionsAction = New-ScheduledTaskAction -Execute "wscript.exe" `
    -Argument "`"$hiddenLauncher`" `"$positionsScript`""
$positionsTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)

Register-ScheduledTask -TaskName $positionsTaskName -Action $positionsAction -Trigger $positionsTrigger `
    -Settings $settings -Force | Out-Null

Write-Host "Tarea '$marketTaskName' registrada: motor de mercado, cada 4 horas."
Write-Host "Tarea '$positionsTaskName' registrada: motor de posiciones, cada 5 minutos."
Write-Host "Ninguna permite corridas superpuestas (MultipleInstances=IgnoreNew)."
Write-Host ""
Write-Host "Ver estado:    Get-ScheduledTaskInfo -TaskName `"$marketTaskName`""
Write-Host "               Get-ScheduledTaskInfo -TaskName `"$positionsTaskName`""
Write-Host "Correr ahora:  Start-ScheduledTask -TaskName `"$marketTaskName`""
Write-Host "               Start-ScheduledTask -TaskName `"$positionsTaskName`""
Write-Host "Eliminar:      Unregister-ScheduledTask -TaskName `"$marketTaskName`" -Confirm:`$false"
Write-Host "               Unregister-ScheduledTask -TaskName `"$positionsTaskName`" -Confirm:`$false"
