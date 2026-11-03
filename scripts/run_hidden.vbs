' Lanza un script de PowerShell sin ventana visible, para las tareas programadas de
' Windows del proyecto (ver setup_task_scheduler.ps1). -WindowStyle Hidden en
' powershell.exe NO alcanza cuando lo dispara el Programador de Tareas: igual asigna
' una consola y la muestra por un instante (el clásico "flash" de CMD cada 5 min).
' WScript.Shell.Run con el tercer argumento en 0 evita eso por completo — ni el
' PowerShell ni el cmd/python que arranca adentro (ver run_scheduled*.ps1) llegan a
' mostrar ventana.
'
' Uso (desde una tarea programada): wscript.exe run_hidden.vbs "<ruta al .ps1>"
Set objShell = CreateObject("WScript.Shell")
scriptPath = WScript.Arguments(0)
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & scriptPath & """", 0, False
