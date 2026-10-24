import asyncio
import logging
import os
from datetime import date
from duration import parse_duration


from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup)
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.utils.token import TokenValidationError

from analytics import averages, build_insights, top_triggers
from db import Database
from models import CheckIn, Impulse, Technique
from planner import DEFAULT_TASKS, build_plan, format_plan
from techniques import TechniquesError, load_techniques, pick_technique

STATS_DAYS = 30
HISTORY_DAYS = 90      # за сколько дней учитываем оценки техник

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

FALLBACK_TEXT = (
    "Подходящей техники сейчас не нашлось. Общий вариант: подожди "
    "10 секунд, потряси кистями и потом реши, брать ли телефон. "
    "Импульс записан."
)

router = Router()


# ---------- состояния диалогов ----------
class CheckinForm(StatesGroup):
    mood = State()
    energy = State()
    stress = State()
    episode = State()
    minutes = State()


class ImpulseForm(StatesGroup):
    trigger = State()
    intensity = State()


# ---------- клавиатуры ----------
def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CHECKIN), KeyboardButton(text=BTN_IMPULSE)],
            [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_PLAN)],
        ],
        resize_keyboard=True,
    )


def number_kb(prefix: str, numbers: range, per_row: int) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=str(n), callback_data=f"{prefix}:{n}")
               for n in numbers]
    rows = [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def scale_kb(prefix: str) -> InlineKeyboardMarkup:
    return number_kb(prefix, range(1, 11), 5)


def episode_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да", callback_data="episode:1"),
        InlineKeyboardButton(text="Нет", callback_data="episode:0"),
    ]])


def trigger_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"trigger:{key}")]
        for key, label in TRIGGER_LABELS.items()
    ])


def helped_kb(impulse_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Помогло",
                             callback_data=f"helped:{impulse_id}:1"),
        InlineKeyboardButton(text="Нет",
                             callback_data=f"helped:{impulse_id}:0"),
    ]])


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


# ---------- меню: /start, статистика, план ----------
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
        header = "Check-in'ов пока нет, поэтому беру базовую нагрузку.\n\n"
    await message.answer(header + format_plan(plan))


# ---------- вечерний check-in ----------
DURATION_EXAMPLES = ("Например: 45 (минуты), 1.5 ч, 2 ч 30 мин или 1:30. "
                     "Не больше 24 часов.")
DURATION_PROMPT = "Сколько времени это длилось? " + DURATION_EXAMPLES

@router.message(Command("checkin"))
@router.message(F.text == BTN_CHECKIN)
async def start_checkin(message: Message, state: FSMContext) -> None:
    await state.clear()                      # если был незаконченный диалог
    await state.set_state(CheckinForm.mood)
    await message.answer(
        "Вечерний check-in. Как настроение сегодня?\n"
        "1 — очень плохое, 10 — отличное.",
        reply_markup=scale_kb("mood"),
    )


@router.callback_query(CheckinForm.mood, F.data.startswith("mood:"))
async def checkin_mood(call: CallbackQuery, state: FSMContext) -> None:
    value = int(call.data.split(":")[1])
    await state.update_data(mood=value)
    await state.set_state(CheckinForm.energy)
    await call.message.edit_text(f"Настроение: {value}")
    await call.message.answer(
        "Какая сегодня была энергия?\n1 — совсем нет сил, 10 — много сил.",
        reply_markup=scale_kb("energy"),
    )
    await call.answer()


@router.callback_query(CheckinForm.energy, F.data.startswith("energy:"))
async def checkin_energy(call: CallbackQuery, state: FSMContext) -> None:
    value = int(call.data.split(":")[1])
    await state.update_data(energy=value)
    await state.set_state(CheckinForm.stress)
    await call.message.edit_text(f"Энергия: {value}")
    await call.message.answer(
        "Какой сегодня был уровень стресса?\n1 — спокойно, 10 — очень сильный.",
        reply_markup=scale_kb("stress"),
    )
    await call.answer()


@router.callback_query(CheckinForm.stress, F.data.startswith("stress:"))
async def checkin_stress(call: CallbackQuery, state: FSMContext) -> None:
    value = int(call.data.split(":")[1])
    await state.update_data(stress=value)
    await state.set_state(CheckinForm.episode)
    await call.message.edit_text(f"Стресс: {value}")
    await call.message.answer(
        "Был ли сегодня эпизод (например, залипание в телефоне дольше, "
        "чем хотелось)?",
        reply_markup=episode_kb(),
    )
    await call.answer()


async def save_checkin(telegram_id: int, state: FSMContext, db: Database,
                       episode: bool, minutes: int) -> None:
    data = await state.get_data()
    uid = db.get_or_create_user(telegram_id)
    db.add_checkin(uid, CheckIn(
        date=date.today(),
        mood=data["mood"], energy=data["energy"], stress=data["stress"],
        episode=episode, episode_minutes=minutes,
    ))
    await state.clear()


CHECKIN_DONE = ("Check-in за сегодня сохранён. Нажми «План на день» или "
                "«Статистика», чтобы увидеть обновлённые данные.")


@router.callback_query(CheckinForm.episode, F.data.startswith("episode:"))
async def checkin_episode(call: CallbackQuery, state: FSMContext,
                          db: Database) -> None:
    had_episode = call.data.split(":")[1] == "1"
    if not had_episode:
        await call.message.edit_text("Эпизод: нет")
        await save_checkin(call.from_user.id, state, db,
                           episode=False, minutes=0)
        await call.message.answer(CHECKIN_DONE)
    else:
        await state.set_state(CheckinForm.minutes)
        await call.message.edit_text("Эпизод: да")
        await call.message.answer(DURATION_PROMPT)
    await call.answer()


@router.message(CheckinForm.minutes)
async def checkin_minutes(message: Message, state: FSMContext,
                          db: Database) -> None:
    try:
        minutes = parse_duration(message.text or "")
    except ValueError:
        await message.answer("Не получилось понять. " + DURATION_EXAMPLES)
        return
    await save_checkin(message.from_user.id, state, db,
                       episode=True, minutes=minutes)
    await message.answer(CHECKIN_DONE)


# ---------- сценарий «Тянет» ----------
@router.message(Command("impulse"))
@router.message(F.text == BTN_IMPULSE)
async def start_impulse(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ImpulseForm.trigger)
    await message.answer("Что сейчас ближе всего к тому, что происходит?",
                         reply_markup=trigger_kb())


@router.callback_query(ImpulseForm.trigger, F.data.startswith("trigger:"))
async def impulse_trigger(call: CallbackQuery, state: FSMContext) -> None:
    key = call.data.split(":")[1]
    if key not in TRIGGER_LABELS:
        await call.answer()
        return
    await state.update_data(trigger=key)
    await state.set_state(ImpulseForm.intensity)
    await call.message.edit_text(f"Триггер: {TRIGGER_LABELS[key]}")
    await call.message.answer(
        "Насколько сильно тянет?\n1 — слабо, 5 — очень сильно.",
        reply_markup=number_kb("intensity", range(1, 6), 5),
    )
    await call.answer()


@router.callback_query(ImpulseForm.intensity, F.data.startswith("intensity:"))
async def impulse_intensity(call: CallbackQuery, state: FSMContext,
                            db: Database, techs: list[Technique]) -> None:
    intensity = int(call.data.split(":")[1])
    trigger = (await state.get_data())["trigger"]
    await state.clear()
    await call.message.edit_text(f"Интенсивность: {intensity}")

    uid = db.get_or_create_user(call.from_user.id)
    impulse_id = db.add_impulse(uid, Impulse(date.today(), trigger, intensity))

    history = db.get_impulses(uid, HISTORY_DAYS)
    tech = pick_technique(techs, trigger, intensity, history)
    if tech is None:                         # импульс уже сохранён
        await call.message.answer(FALLBACK_TEXT)
    else:
        db.set_technique(impulse_id, tech.id)
        await call.message.answer(
            f"Попробуй: {tech.title}\n\n{tech.text}\n\nПомогло?",
            reply_markup=helped_kb(impulse_id),
        )
    await call.answer()


@router.callback_query(F.data.startswith("helped:"))
async def impulse_helped(call: CallbackQuery, db: Database) -> None:
    _, impulse_id, flag = call.data.split(":")
    try:
        db.set_helped(int(impulse_id), flag == "1")
    except ValueError:
        await call.answer("Не нашла этот импульс", show_alert=True)
        return
    await call.message.edit_reply_markup(reply_markup=None)
    if flag == "1":
        await call.message.answer("Хорошо, это запомнено.")
    else:
        await call.message.answer(
            "Принято. В следующий раз предложу другую технику."
        )
    await call.answer()

def read_token() -> str:
    """Токен из BOT_TOKEN без пробелов и кавычек по краям."""
    return os.getenv("BOT_TOKEN", "").strip().strip("\"'")
# ---------- запуск ----------
async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    token = read_token()
    if not token:
        raise SystemExit("Не задан токен. Выполните: "
                         "set BOT_TOKEN=токен_от_BotFather")

    try:
        techs = load_techniques()
    except TechniquesError as e:
        raise SystemExit(f"Ошибка файла техник: {e}")

    proxy = os.getenv("PROXY_URL")
    session = AiohttpSession(proxy=proxy) if proxy else None
    try:
        bot = Bot(token, session=session)
    except TokenValidationError:
        raise SystemExit("Токен выглядит неверно. Он должен быть вида "
                         "123456789:AAH... Скопируйте его у @BotFather "
                         "целиком, без пробелов и кавычек.")

    db = Database("habit_bot.db")
    db.init_schema()
    dp = Dispatcher(db=db, techs=techs)
    dp.include_router(router)

    try:
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        raise SystemExit("Telegram не принял токен. Проверьте, что он "
                         "актуален (возможно, его перевыпустили через /revoke).")
    finally:
        db.close()
        await bot.session.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())