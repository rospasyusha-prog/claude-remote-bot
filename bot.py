# Telegram-бот для удалённого управления Claude Code агентами
import os
import sys
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()

# Защита от запуска нескольких копий: создаём lock-файл
LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.lock")

def acquire_lock():
    """Создаёт lock-файл с PID. Если файл уже есть и процесс жив — выходим."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            # Проверяем, жив ли процесс
            import psutil
            if psutil.pid_exists(old_pid):
                print(f"Бот уже запущен (PID={old_pid}). Выход.")
                sys.exit(0)
        except Exception:
            pass  # Файл повреждён — перезапишем
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

def release_lock():
    """Удаляет lock-файл при остановке."""
    try:
        os.remove(LOCK_FILE)
    except Exception:
        pass

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
CLAUDE_PATH = os.getenv("CLAUDE_PATH", "claude")
WORK_DIR = os.getenv("WORK_DIR", os.path.expanduser("~"))


def is_authorized(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    await update.message.reply_text(
        "Привет! Я управляю Claude Code агентами.\n\n"
        "Просто отправь задачу текстом — я запущу агента и пришлю результат.\n\n"
        "Команды:\n"
        "/start — это сообщение\n"
        "/status — проверить статус\n"
        "/cancel — отменить текущую задачу"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    await update.message.reply_text("Бот работает. Отправь задачу текстом.")


async def run_claude(prompt: str) -> str:
    """Запускает claude CLI с заданным промптом и возвращает результат."""
    try:
        # На Windows .cmd файлы нужно запускать через shell
        # Экранируем промпт для безопасной передачи в командную строку
        safe_prompt = prompt.replace('"', '\\"')
        command = f'"{CLAUDE_PATH}" --print "{safe_prompt}"'
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=WORK_DIR
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode == 0:
            result = stdout.decode("utf-8", errors="replace").strip()
            return result if result else "Агент завершил работу (нет вывода)."
        else:
            error = stderr.decode("utf-8", errors="replace").strip()
            return f"Ошибка агента (код {proc.returncode}):\n{error}"
    except asyncio.TimeoutError:
        return "Время выполнения истекло (5 минут). Попробуй более короткую задачу."
    except FileNotFoundError:
        return f"claude CLI не найден по пути: {CLAUDE_PATH}\nПроверь CLAUDE_PATH в .env файле."
    except Exception as e:
        return f"Ошибка: {e}"


# Хранилище активных задач
active_tasks: dict[int, asyncio.Task] = {}


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Доступ запрещён.")
        return

    user_id = update.effective_user.id
    prompt = update.message.text.strip()

    if not prompt:
        return

    # Отправляем подтверждение
    status_msg = await update.message.reply_text(
        f"Запускаю агента...\nЗадача: {prompt[:100]}{'...' if len(prompt) > 100 else ''}"
    )

    # Запускаем claude в фоне
    async def run_task():
        result = await run_claude(prompt)
        # Telegram ограничивает сообщения до 4096 символов
        if len(result) > 4000:
            # Отправляем по частям
            for i in range(0, len(result), 4000):
                await update.message.reply_text(result[i:i+4000])
        else:
            await update.message.reply_text(f"Результат:\n\n{result}")
        await status_msg.delete()
        active_tasks.pop(user_id, None)

    task = asyncio.create_task(run_task())
    active_tasks[user_id] = task


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Доступ запрещён.")
        return

    user_id = update.effective_user.id
    task = active_tasks.pop(user_id, None)

    if task and not task.done():
        task.cancel()
        await update.message.reply_text("Задача отменена.")
    else:
        await update.message.reply_text("Нет активных задач.")


def main():
    acquire_lock()
    try:
        if not BOT_TOKEN:
            print("Ошибка: BOT_TOKEN не задан в .env файле")
            return
        if not ALLOWED_USER_ID:
            print("Ошибка: ALLOWED_USER_ID не задан в .env файле")
            return

        app = Application.builder().token(BOT_TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("status", status))
        app.add_handler(CommandHandler("cancel", cancel))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        print("Бот запущен. Нажми Ctrl+C для остановки.")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        release_lock()


if __name__ == "__main__":
    main()
