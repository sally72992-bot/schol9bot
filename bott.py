import json
import logging
import os
from datetime import datetime, date, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Tashkent")
TZ = ZoneInfo(TIMEZONE_NAME)

DATA_DIR = Path(os.getenv("DATA_DIR", "."))
SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"
SENT_FILE = DATA_DIR / "sent_reminders.json"

# Python weekday: Monday=0 ... Sunday=6
WEEKDAYS = {
    0: ("Понедельник", [
        "Английский", "Физика", "Литература", "Химия",
        "География", "Английский", "Русский язык",
    ]),
    1: ("Вторник", [
        "География / экономика", "Геометрия", "Физика", "Английский",
        "Узбекский язык", "История", "Алгебра", "Русский язык",
    ]),
    2: ("Среда", [
        "Русский язык", "Геометрия", "История Узбекистана", "Информатика",
        "Английский", "Физкультура", "Узбекский язык",
    ]),
    3: ("Четверг", [
        "ОГП", "Физкультура", "Воспитание", "Биология",
        "Узбекский язык", "Биология", "Алгебра",
    ]),
    4: ("Пятница", [
        "Информатика", "Всемирная история", "Алгебра", "Химия",
        "Русский язык", "Литература", "Геометрия", "Английский",
    ]),
}

LESSON_MINUTES = 45
SHORT_BREAK = 5
LONG_BREAK_AFTER = 4
LONG_BREAK = 20
FIRST_LESSON = time(8, 0)

KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📚 Расписание на сегодня", "📅 Расписание на завтра"],
        ["🔔 Следующий урок", "🕒 Время звонков"],
    ],
    resize_keyboard=True,
)

def load_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(path: Path, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp_path.replace(path)

def subscribers():
    return set(int(x) for x in load_json(SUBSCRIBERS_FILE, []))

def add_subscriber(chat_id: int):
    current = subscribers()
    current.add(chat_id)
    save_json(SUBSCRIBERS_FILE, sorted(current))

def lesson_start(index: int) -> datetime:
    """index is zero-based lesson index."""
    minutes = index * (LESSON_MINUTES + SHORT_BREAK)
    if index >= LONG_BREAK_AFTER:
        minutes += LONG_BREAK - SHORT_BREAK
    dt = datetime.combine(date.today(), FIRST_LESSON, tzinfo=TZ) + timedelta(minutes=minutes)
    return dt

def starts_for_day(day: date):
    if day.weekday() not in WEEKDAYS:
        return []
    items = []
    for index, subject in enumerate(WEEKDAYS[day.weekday()][1]):
        start_minutes = index * (LESSON_MINUTES + SHORT_BREAK)
        if index >= LONG_BREAK_AFTER:
            start_minutes += LONG_BREAK - SHORT_BREAK
        start_dt = datetime.combine(day, FIRST_LESSON, tzinfo=TZ) + timedelta(minutes=start_minutes)
        end_dt = start_dt + timedelta(minutes=LESSON_MINUTES)
        items.append((subject, start_dt, end_dt))
    return items

def next_school_day(day: date, include_today=False):
    candidate = day if include_today else day + timedelta(days=1)
    for _ in range(8):
        if candidate.weekday() in WEEKDAYS:
            return candidate
        candidate += timedelta(days=1)
    return day

def format_day(day: date) -> str:
    if day.weekday() not in WEEKDAYS:
        return "В этот день уроков нет."
    day_name, subjects = WEEKDAYS[day.weekday()]
    lines = [f"📚 Расписание на {day_name.lower()} ({day.strftime('%d.%m')}):"]
    for i, (subject, start, end) in enumerate(starts_for_day(day), start=1):
        lines.append(f"{i}. {start:%H:%M}–{end:%H:%M} — {subject}")
    return "\n".join(lines)

def next_lesson_text(now: datetime) -> str:
    today = now.date()
    if today.weekday() in WEEKDAYS:
        for i, (subject, start, end) in enumerate(starts_for_day(today), start=1):
            if now < start:
                mins = int((start - now).total_seconds() // 60)
                return (
                    f"🔔 Следующий урок: {subject}\n"
                    f"Начало: {start:%H:%M} (урок №{i})\n"
                    f"До начала: примерно {mins} мин."
                )
        return "На сегодня уроки закончились! 🎉"
    day = next_school_day(today, include_today=False)
    first = starts_for_day(day)[0]
    return (
        f"🔔 Ближайший учебный день — {WEEKDAYS[day.weekday()][0].lower()}.\n"
        f"Первый урок: {first[0]} в {first[1]:%H:%M}."
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    add_subscriber(chat_id)
    await update.message.reply_text(
        "Привет! 👋 Я бот школьного расписания.\n\n"
        "Я буду напоминать за 10 и за 5 минут до каждого урока.\n"
        "Оставь бота запущенным и нажми нужную кнопку ниже.",
        reply_markup=KEYBOARD,
    )

async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ)
    await update.message.reply_text(format_day(now.date()), reply_markup=KEYBOARD)

async def tomorrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ)
    day = next_school_day(now.date(), include_today=False)
    await update.message.reply_text(format_day(day), reply_markup=KEYBOARD)

async def next_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(next_lesson_text(datetime.now(TZ)), reply_markup=KEYBOARD)

async def bells_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ)
    day = now.date()
    if day.weekday() not in WEEKDAYS:
        day = next_school_day(day, include_today=False)
    lines = [f"🕒 Время звонков на {WEEKDAYS[day.weekday()][0].lower()}:"]
    for i, (subject, start, end) in enumerate(starts_for_day(day), start=1):
        lines.append(f"{i}. {start:%H:%M}–{end:%H:%M} — {subject}")
    lines.append("\nПеремены: 5 минут, после 4-го урока — 20 минут.")
    await update.message.reply_text("\n".join(lines), reply_markup=KEYBOARD)

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text == "📚 Расписание на сегодня":
        await today_cmd(update, context)
    elif text == "📅 Расписание на завтра":
        await tomorrow_cmd(update, context)
    elif text == "🔔 Следующий урок":
        await next_cmd(update, context)
    elif text == "🕒 Время звонков":
        await bells_cmd(update, context)
    else:
        await update.message.reply_text(
            "Выбери действие кнопкой или используй /today, /tomorrow, /next, /bells.",
            reply_markup=KEYBOARD,
        )

async def reminder_check(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ)
    if now.weekday() not in WEEKDAYS:
        return

    sent = load_json(SENT_FILE, {})
    today_key = now.strftime("%Y-%m-%d")
    # Keep only the last 3 days so the JSON file doesn't grow forever.
    cutoff = (now.date() - timedelta(days=3)).isoformat()
    sent = {k: v for k, v in sent.items() if k.split("|", 1)[0] >= cutoff}

    for i, (subject, start, end) in enumerate(starts_for_day(now.date()), start=1):
        for offset in (10, 5):
            reminder_time = start - timedelta(minutes=offset)
            # Send within a 60-second window; the repeating job checks every 15 seconds.
            if reminder_time <= now < reminder_time + timedelta(seconds=60):
                key = f"{today_key}|{i}|{offset}"
                if key in sent:
                    continue
                message = (
                    f"⏰ Через {offset} минут урок №{i}!\n"
                    f"📘 Предмет: {subject}\n"
                    f"🕒 Начало: {start:%H:%M}"
                )
                for chat_id in subscribers():
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=message)
                    except Exception:
                        logger.exception("Не удалось отправить напоминание в чат %s", chat_id)
                sent[key] = True
                save_json(SENT_FILE, sent)

def main():
    if not TOKEN:
        raise RuntimeError(
            "Не задан TELEGRAM_BOT_TOKEN. Добавь токен в Environment Variables на хостинге."
        )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("tomorrow", tomorrow_cmd))
    app.add_handler(CommandHandler("next", next_cmd))
    app.add_handler(CommandHandler("bells", bells_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.job_queue.run_repeating(reminder_check, interval=15, first=2, name="lesson-reminders")
    logger.info("Бот запускается. Часовой пояс: %s", TIMEZONE_NAME)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
