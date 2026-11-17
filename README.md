# Claude Remote Bot

Telegram-бот для удалённого управления Claude Code агентами с телефона.

## Установка

1. Клонируй репо:
   ```
   git clone https://github.com/rospasyusha-prog/claude-remote-bot.git
   cd claude-remote-bot
   ```

2. Установи зависимости:
   ```
   pip install -r requirements.txt
   ```

3. Создай файл .env на основе .env.example:
   ```
   copy .env.example .env
   ```

4. Заполни .env:
   - BOT_TOKEN — токен от @BotFather
   - ALLOWED_USER_ID — твой Telegram ID (узнай у @userinfobot)
   - WORK_DIR — папка с твоим проектом

5. Запусти бота:
   ```
   python bot.py
   ```
   или двойным кликом на `start.bat`

## Использование

Открой бота в Telegram и отправь любую задачу текстом.
Агент выполнит её и пришлёт результат прямо в чат.

Команды:
- `/start` — справка
- `/status` — проверить статус
- `/cancel` — отменить текущую задачу
