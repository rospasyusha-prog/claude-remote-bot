' Запуск бота без окна консоли, защита от дублирования
Dim pythonw, botScript, lockFile, pid, fso, f

pythonw  = "C:\Users\nastya64rus_ekb\AppData\Local\Programs\Python\Python312\pythonw.exe"
botScript = "C:\Users\nastya64rus_ekb\Desktop\rosi-workspace\claude-remote-bot\bot.py"
lockFile  = "C:\Users\nastya64rus_ekb\Desktop\rosi-workspace\claude-remote-bot\bot.lock"

Set fso = CreateObject("Scripting.FileSystemObject")

' Если lock существует — бот уже запущен, выходим
If fso.FileExists(lockFile) Then
    WScript.Quit
End If

' Запускаем бота (0 = скрыто, False = не ждать завершения)
Set objShell = CreateObject("WScript.Shell")
objShell.Run """" & pythonw & """ """ & botScript & """", 0, False
