@echo off
:: Скрипт перезапуска бота — убивает все копии и запускает одну новую

set BOT_DIR=C:\Users\nastya64rus_ekb\Desktop\rosi-workspace\claude-remote-bot
set PYTHONW=C:\Users\nastya64rus_ekb\AppData\Local\Programs\Python\Python312\pythonw.exe

echo Останавливаю все копии бота...
wmic process where "commandline like '%%bot.py%%'" delete >nul 2>&1
timeout /t 2 /nobreak >nul

echo Удаляю lock-файл...
if exist "%BOT_DIR%\bot.lock" del /f "%BOT_DIR%\bot.lock"

echo Запускаю бота...
start "" /B "%PYTHONW%" "%BOT_DIR%\bot.py"

echo Готово. Бот запущен.
