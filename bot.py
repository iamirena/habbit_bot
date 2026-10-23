import asyncio
import logging
import os

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from analytics import averages, build_insights, top_triggers
from db import Database
from models import CheckIn, Impulse
from planner import DEFAULT_TASKS, build_plan, format_plan

STATS_DAYS = 30

# Русские подписи триггеров (ключи совпадают с techniques.json)
TRIGGER_LABELS = {
    "boredom": "скука / нечем заняться",
    "fatigue": "усталость",
    "stress": "стресс",
}

BTN_CHECKIN = "Вечерний check-in"
BTN_IMPULSE = "Тянет"
BTN_STATS = "Статистика"
BTN_PLAN = "План на день"

DISCLAIMER = (
    "Этот бот помогает отслеживать состояние и привычки и составлять "
    "реалистичный план дня. Он не заменяет специалиста: при сильном "
    "дискомфорте лучше обратиться к психологу или врачу."
)

router = Router()


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CHECKIN), KeyboardButton(text=BTN_IMPULSE)],
            [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_PLAN)],
        ],
        resize_keyboard=True,
    )


# ---------- форматирование ----------
def format_stats(checkins: list[CheckIn], impulses: list[Impulse]) -> str:
    a = averages(checkins)
    if a is None:
        return ("Пока нет данных. Заполни вечерний check-in, "
                "и здесь появится статистика.")

    lines = [
        f"Статистика за {STATS_DAYS} дней (дней с записью: {a['days']})",
        "",
        f"Настроение: {a['mood']:.1f} из 10",
        f"Энергия: {a['energy']:.1f} из 10",
        f"Стресс: {a['stress']:.1f} из 10",
        "",
        f"Дней с эпизодами: {a['episode_days']}",
    ]
    if a["avg_episode_minutes"] is not None:
        lines.append(f"В дни с эпизодом в среднем {a['avg_episode_minutes']:.0f} мин")

    triggers = top_triggers(impulses)
    if triggers:
        lines += ["", "Частые триггеры:"]
        for key, count in triggers:
            label = TRIGGER_LABELS.get(key, key)
            lines.append(f"• {label}: {count}")

    lines.append("")
    if a["days"] < 7:
        lines.append("Наблюдения появятся, когда накопится хотя бы 7 дней записей.")
    else:
        insights = build_insights(checkins, impulses)
        if insights:
            lines.append("Наблюдения:")
            lines += [f"• {text}" for text in insights]
        else:
            lines.append("Заметных закономерностей пока не видно.")
    return "\n".join(lines)


# ---------- хендлеры ----------
@router.message(CommandStart())
async def cmd_start(message: Message, db: Database) -> None:
    db.get_or_create_user(message.from_user.id)
    await message.answer(
        "Привет! Я помогу отслеживать состояние и нежелательные привычки "
        "(например, залипание в телефоне).\n\n" + DISCLAIMER,
        reply_markup=main_menu(),
    )


@router.message(Command("stats"))
@router.message(F.text == BTN_STATS)
async def cmd_stats(message: Message, db: Database) -> None:
    uid = db.get_or_create_user(message.from_user.id)
    checkins = db.get_checkins(uid, STATS_DAYS)
    impulses = db.get_impulses(uid, STATS_DAYS)
    await message.answer(format_stats(checkins, impulses))


@router.message(Command("plan"))
@router.message(F.text == BTN_PLAN)
async def cmd_plan(message: Message, db: Database) -> None:
    uid = db.get_or_create_user(message.from_user.id)
    checkins = db.get_checkins(uid, STATS_DAYS)
    last = checkins[-1] if checkins else None

    plan = build_plan(
        DEFAULT_TASKS,
        energy=last.energy if last else None,
        stress=last.stress if last else None,
    )
    if last:
        header = f"Учтён последний check-in ({last.date.strftime('%d.%m')}).\n\n"
    else:
        header = ("Check-in'ов пока нет, поэтому беру базовую нагрузку.\n\n")
    await message.answer(header + format_plan(plan))


# Заглушки: во второй части заменим на настоящие сценарии
@router.message(F.text.in_({BTN_CHECKIN, BTN_IMPULSE}))
async def not_ready(message: Message) -> None:
    await message.answer("Этот раздел появится в следующей части.")


# ---------- запуск ----------
async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("Не задана переменная окружения BOT_TOKEN")

    db = Database("habit_bot.db")
    db.init_schema()

    proxy = os.getenv("PROXY_URL")
    session = AiohttpSession(proxy=proxy) if proxy else None
    bot = Bot(token, session=session)
    dp = Dispatcher(db=db)          # db будет доступна хендлерам как аргумент
    dp.include_router(router)

    try:
        await dp.start_polling(bot)
    finally:
        db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())