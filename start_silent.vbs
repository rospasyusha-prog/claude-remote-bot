' Запуск Telegram-бота Claude Remote Control без окна консоли
Set objShell = CreateObject("WScript.Shell")
strDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
objShell.CurrentDirectory = strDir
objShell.Run """C:\Users\nastya64rus_ekb\AppData\Local\Programs\Python\Python312\pythonw.exe""" & " """ & strDir & "\bot.py""", 0, False
