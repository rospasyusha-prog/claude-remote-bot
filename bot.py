# Telegram-бот для удалённого управления Claude Code агентами и сайтом rosi
import os
import sys
import asyncio
import psutil
import datetime
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

load_dotenv()

BOT_TOKEN      = os.getenv("BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
CLAUDE_PATH    = os.getenv("CLAUDE_PATH", "claude")
WORK_DIR       = os.getenv("WORK_DIR", os.path.expanduser("~"))
SITE_URL       = os.getenv("SITE_URL", "https://rosi.timeweb.app")
SITE_REPO_DIR  = os.getenv("SITE_REPO_DIR", WORK_DIR)  # путь к клону rosi на ПК (если есть)

LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.lock")

# ── Защита от дублирования ───────────────────────────────────────────────────

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            if psutil.pid_exists(old_pid):
                print(f"Бот уже запущен (PID={old_pid}). Выход.")
                sys.exit(0)
        except Exception:
            pass
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

def release_lock():
    try:
        os.remove(LOCK_FILE)
    except Exception:
        pass

# ── Авторизация ──────────────────────────────────────────────────────────────

def auth(update: Update) -> bool:
    return update.effective_user.id == ALLOWED_USER_ID

async def deny(update: Update):
    await update.message.reply_text("Доступ запрещён.")

# ── Запуск shell-команды ─────────────────────────────────────────────────────

async def run_shell(cmd: str, cwd: str = None, timeout: int = 60) -> str:
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or WORK_DIR,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode == 0:
            return out or "(нет вывода)"
        return f"Код {proc.returncode}:\n{err or out}"
    except asyncio.TimeoutError:
        return "Время вышло."
    except Exception as e:
        return f"Ошибка: {e}"

# ── Запуск Claude агента ─────────────────────────────────────────────────────

async def run_claude(prompt: str) -> str:
    safe = prompt.replace('"', '\\"')
    cmd  = f'"{CLAUDE_PATH}" --print "{safe}"'
    return await run_shell(cmd, cwd=WORK_DIR, timeout=300)

# ── Отправка длинного текста по частям ──────────────────────────────────────

async def send_long(update: Update, text: str):
    text = text.strip() or "(пусто)"
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i+4000])

# ── История задач ────────────────────────────────────────────────────────────

task_history: list[dict] = []   # {time, prompt, result}
active_tasks: dict[int, asyncio.Task] = {}

# ── Мониторинг сайта ─────────────────────────────────────────────────────────

monitor_enabled  = True        # включён по умолчанию
monitor_interval = 5 * 60      # проверка каждые 5 минут
site_was_up      = True        # последнее известное состояние сайта
monitor_task: asyncio.Task | None = None

async def check_site_up() -> tuple[bool, str]:
    """Возвращает (доступен, описание)."""
    try:
        proc = await asyncio.create_subprocess_shell(
            f'curl -o /dev/null -s -w "%{{http_code}}" --max-time 10 {SITE_URL}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        code = stdout.decode().strip()
        up = code.startswith("2") or code.startswith("3")
        return up, f"HTTP {code}"
    except Exception as e:
        return False, str(e)

async def monitor_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Задача для job_queue: проверяет сайт и шлёт уведомление при смене статуса."""
    global site_was_up
    if not monitor_enabled:
        return
    up, desc = await check_site_up()
    if up and not site_was_up:
        site_was_up = True
        await ctx.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=f"✅ Сайт снова работает!\n{SITE_URL}\n{desc}",
        )
    elif not up and site_was_up:
        site_was_up = False
        await ctx.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=f"🚨 Сайт не отвечает!\n{SITE_URL}\n{desc}\n\nПроверяю каждые {monitor_interval//60} мин.",
        )

# ════════════════════════════════════════════════════════════════════════════
#  КОМАНДЫ
# ════════════════════════════════════════════════════════════════════════════

# /start
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    text = (
        "Привет! Управляю сайтом и агентами прямо отсюда.\n\n"
        "*Агент Claude*\n"
        "Просто отправь задачу текстом — агент выполнит её.\n\n"
        "*Система*\n"
        "/sysinfo — CPU, RAM, диск\n\n"
        "*Файлы проекта*\n"
        "/files `[путь]` — список файлов\n"
        "/read `<файл>` — прочитать файл\n\n"
        "*Git*\n"
        "/gitstatus — статус репо\n"
        "/gitlog — последние коммиты\n"
        "/gitpull — стянуть изменения\n"
        "/gitpush `<сообщение>` — коммит и пуш\n"
        "/diff — что изменилось\n\n"
        "*Сайт*\n"
        "/sitecheck — проверить, что сайт живой\n"
        "/deploy — задеплоить последний коммит\n\n"
        "/monitor — статус мониторинга сайта\n"
        "/monitor on/off — включить/выключить\n\n"
        "/history — история последних задач\n"
        "/cancel — отменить текущую задачу\n"
        "/status — состояние бота\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# /status
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    active = len([t for t in active_tasks.values() if not t.done()])
    await update.message.reply_text(
        f"Бот работает.\nАктивных задач: {active}\nВ истории: {len(task_history)}"
    )

# /sysinfo
async def cmd_sysinfo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    cpu  = psutil.cpu_percent(interval=1)
    ram  = psutil.virtual_memory()
    disk = psutil.disk_usage(WORK_DIR[:3] if os.name == "nt" else "/")
    uptime_sec = datetime.datetime.now().timestamp() - psutil.boot_time()
    h, r = divmod(int(uptime_sec), 3600)
    m = r // 60
    text = (
        f"*Система*\n"
        f"CPU: {cpu}%\n"
        f"RAM: {ram.used // 1024**2} / {ram.total // 1024**2} МБ ({ram.percent}%)\n"
        f"Диск: {disk.used // 1024**3} / {disk.total // 1024**3} ГБ ({disk.percent}%)\n"
        f"Аптайм: {h}ч {m}мин"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# /files [путь]
async def cmd_files(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    rel = " ".join(ctx.args) if ctx.args else "."
    target = os.path.join(SITE_REPO_DIR, rel)
    if not os.path.exists(target):
        return await update.message.reply_text(f"Путь не найден: {target}")
    try:
        entries = sorted(Path(target).iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = []
        for e in entries[:60]:
            icon = "📁" if e.is_dir() else "📄"
            lines.append(f"{icon} {e.name}")
        text = f"*{rel}*\n" + "\n".join(lines)
        if len(entries) > 60:
            text += f"\n…ещё {len(entries)-60} файлов"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as ex:
        await update.message.reply_text(f"Ошибка: {ex}")

# /read <файл>
async def cmd_read(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    if not ctx.args:
        return await update.message.reply_text("Использование: /read <путь к файлу>")
    rel  = " ".join(ctx.args)
    path = os.path.join(SITE_REPO_DIR, rel)
    if not os.path.isfile(path):
        return await update.message.reply_text(f"Файл не найден: {path}")
    try:
        size = os.path.getsize(path)
        if size > 50_000:
            return await update.message.reply_text(f"Файл слишком большой ({size//1024} КБ). Используй агента.")
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read(4000)
        await send_long(update, f"```\n{content}\n```")
    except Exception as ex:
        await update.message.reply_text(f"Ошибка: {ex}")

# /diff
async def cmd_diff(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    result = await run_shell("git diff HEAD --stat", cwd=SITE_REPO_DIR)
    await send_long(update, f"*Изменения (diff --stat)*\n```\n{result}\n```")

# /gitstatus
async def cmd_gitstatus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    result = await run_shell("git status -s && echo --- && git log -1 --oneline", cwd=SITE_REPO_DIR)
    await send_long(update, f"*Git статус*\n```\n{result}\n```")

# /gitlog
async def cmd_gitlog(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    result = await run_shell(
        'git log -8 --pretty=format:"%h %s (%cr)" --no-merges',
        cwd=SITE_REPO_DIR
    )
    await send_long(update, f"*Последние коммиты*\n```\n{result}\n```")

# /gitpull
async def cmd_gitpull(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    msg = await update.message.reply_text("Тяну изменения...")
    result = await run_shell("git pull origin main", cwd=SITE_REPO_DIR)
    await msg.edit_text(f"*git pull*\n```\n{result}\n```", parse_mode="Markdown")

# /gitpush <сообщение>
async def cmd_gitpush(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    commit_msg = " ".join(ctx.args) if ctx.args else "update via telegram bot"
    msg = await update.message.reply_text("Коммичу и пушу...")
    result = await run_shell(
        f'git add -A && git commit -m "{commit_msg}" && git push origin main',
        cwd=SITE_REPO_DIR
    )
    await msg.edit_text(f"*git push*\n```\n{result}\n```", parse_mode="Markdown")

# /sitecheck
async def cmd_sitecheck(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    msg = await update.message.reply_text(f"Проверяю {SITE_URL}...")
    # curl с таймаутом 10с, возвращаем HTTP-код и время
    result = await run_shell(
        f'curl -o /dev/null -s -w "HTTP %{{http_code}}  время: %{{time_total}}с" --max-time 10 {SITE_URL}',
        timeout=15
    )
    icon = "✅" if "HTTP 2" in result or "HTTP 3" in result else "⚠️"
    await msg.edit_text(f"{icon} {SITE_URL}\n{result}")

# /deploy
async def cmd_deploy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    # Кнопка подтверждения — деплой необратим
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Да, деплоить", callback_data="deploy_confirm"),
        InlineKeyboardButton("Отмена",        callback_data="deploy_cancel"),
    ]])
    await update.message.reply_text(
        "Задеплоить последний коммит main на Timeweb?",
        reply_markup=kb
    )

async def cb_deploy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not auth(update): return await q.edit_message_text("Доступ запрещён.")
    if q.data == "deploy_cancel":
        return await q.edit_message_text("Деплой отменён.")
    await q.edit_message_text("Деплою...")
    # Пушим в origin main — Timeweb подхватывает через webhook/auto-deploy
    result = await run_shell("git push origin main", cwd=SITE_REPO_DIR)
    await q.edit_message_text(f"*Деплой*\n```\n{result}\n```", parse_mode="Markdown")

# /history
async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    if not task_history:
        return await update.message.reply_text("История пуста.")
    lines = []
    for i, t in enumerate(task_history[-10:], 1):
        ts     = t["time"].strftime("%H:%M")
        prompt = t["prompt"][:60] + ("…" if len(t["prompt"]) > 60 else "")
        status = "✅" if t.get("ok") else "❌"
        lines.append(f"{i}. {status} [{ts}] {prompt}")
    await update.message.reply_text("*Последние задачи*\n" + "\n".join(lines), parse_mode="Markdown")

# /monitor on|off|status
async def cmd_monitor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    global monitor_enabled
    arg = ctx.args[0].lower() if ctx.args else "status"
    if arg == "on":
        monitor_enabled = True
        await update.message.reply_text(f"✅ Мониторинг включён. Проверка каждые {monitor_interval//60} мин.")
    elif arg == "off":
        monitor_enabled = False
        await update.message.reply_text("⏸ Мониторинг выключен.")
    else:
        up, desc = await check_site_up()
        icon = "✅" if up else "🚨"
        state = "включён" if monitor_enabled else "выключен"
        await update.message.reply_text(
            f"{icon} Сайт: {desc}\n"
            f"Мониторинг: {state}\n"
            f"Интервал: каждые {monitor_interval//60} мин\n"
            f"URL: {SITE_URL}"
        )

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    uid  = update.effective_user.id
    task = active_tasks.pop(uid, None)
    if task and not task.done():
        task.cancel()
        await update.message.reply_text("Задача отменена.")
    else:
        await update.message.reply_text("Нет активных задач.")

# ── Текстовые сообщения → Claude агент ───────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return await deny(update)
    uid    = update.effective_user.id
    prompt = update.message.text.strip()
    if not prompt:
        return
    status_msg = await update.message.reply_text(
        f"⏳ Запускаю агента...\n{prompt[:80]}{'…' if len(prompt) > 80 else ''}"
    )
    async def run_task():
        result = await run_claude(prompt)
        ok     = not result.startswith("Ошибка") and not result.startswith("Код ")
        task_history.append({
            "time":   datetime.datetime.now(),
            "prompt": prompt,
            "result": result[:200],
            "ok":     ok,
        })
        # Оставляем только 50 последних
        if len(task_history) > 50:
            task_history.pop(0)
        try:
            await status_msg.delete()
        except Exception:
            pass
        await send_long(update, result)
        active_tasks.pop(uid, None)
    t = asyncio.create_task(run_task())
    active_tasks[uid] = t

# ── Запуск ───────────────────────────────────────────────────────────────────

def main():
    acquire_lock()
    try:
        if not BOT_TOKEN:
            print("Ошибка: BOT_TOKEN не задан в .env")
            return
        if not ALLOWED_USER_ID:
            print("Ошибка: ALLOWED_USER_ID не задан в .env")
            return

        async def on_startup(app):
            app.job_queue.run_repeating(monitor_job, interval=monitor_interval, first=10)

        app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()

        app.add_handler(CommandHandler("start",      cmd_start))
        app.add_handler(CommandHandler("status",     cmd_status))
        app.add_handler(CommandHandler("sysinfo",    cmd_sysinfo))
        app.add_handler(CommandHandler("files",      cmd_files))
        app.add_handler(CommandHandler("read",       cmd_read))
        app.add_handler(CommandHandler("diff",       cmd_diff))
        app.add_handler(CommandHandler("gitstatus",  cmd_gitstatus))
        app.add_handler(CommandHandler("gitlog",     cmd_gitlog))
        app.add_handler(CommandHandler("gitpull",    cmd_gitpull))
        app.add_handler(CommandHandler("gitpush",    cmd_gitpush))
        app.add_handler(CommandHandler("sitecheck",  cmd_sitecheck))
        app.add_handler(CommandHandler("deploy",     cmd_deploy))
        app.add_handler(CommandHandler("history",    cmd_history))
        app.add_handler(CommandHandler("monitor",    cmd_monitor))
        app.add_handler(CommandHandler("cancel",     cmd_cancel))
        app.add_handler(CallbackQueryHandler(cb_deploy, pattern="^deploy_"))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        print("Бот запущен.")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        release_lock()


if __name__ == "__main__":
    main()
