import random
from datetime import date, timedelta
from typing import Optional
import argparse

from analytics import averages, build_insights, top_triggers
from db import Database
from models import CheckIn, Impulse
from planner import DEFAULT_TASKS, build_plan, format_plan
from techniques import load_techniques, pick_technique


def _clamp(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))


def seed(db: Database, user_id: int, techs: list,
         days: int = 30, today: Optional[date] = None,
         rng_seed: int = 42) -> None:
    rng = random.Random(rng_seed)
    today = today or date.today()
    history: list[Impulse] = []      # накопленные импульсы для pick_technique

    for offset in range(days - 1, -1, -1):
        d = today - timedelta(days=offset)

        energy = rng.randint(2, 9)
        stress = rng.randint(2, 9)
        mood = _clamp(round(5 + (energy - 5) * 0.4 - (stress - 5) * 0.4
                            + rng.uniform(-1, 1)), 1, 10)

        # вероятность эпизода выше при стрессе и низкой энергии
        p = 0.15
        if stress >= 7:
            p += 0.35
        if energy <= 4:
            p += 0.30
        episode = rng.random() < min(p, 0.9)

        minutes = 0
        if episode:
            minutes = _clamp(round(15 + (10 - energy) * 5 + stress * 3
                                   + rng.randint(-10, 10)), 5, 240)

        db.add_checkin(user_id, CheckIn(d, mood, energy, stress,
                                        episode, minutes))

        # импульсы за день
        for _ in range(rng.randint(0, 2) + (1 if episode else 0)):
            weights = {"boredom": 2, "fatigue": 1, "stress": 1}
            if energy <= 4:
                weights["fatigue"] += 4
            if stress >= 7:
                weights["stress"] += 4
            trigger = rng.choices(list(weights), list(weights.values()))[0]
            intensity = _clamp(rng.randint(1, 3)
                               + (1 if stress >= 7 else 0)
                               + (1 if energy <= 4 else 0), 1, 5)

            imp_id = db.add_impulse(user_id, Impulse(d, trigger, intensity))
            tech = pick_technique(techs, trigger, intensity, history, rng=rng)
            if tech is None:
                history.append(Impulse(d, trigger, intensity, id=imp_id))
                continue
            db.set_technique(imp_id, tech.id)

            helped = None if rng.random() < 0.2 else rng.random() < 0.65
            if helped is not None:
                db.set_helped(imp_id, helped)
            history.append(Impulse(d, trigger, intensity, id=imp_id,
                                   technique_id=tech.id, helped=helped))


if __name__ == "__main__":
    DEFAULT_DB = "habit_bot.db"
DEFAULT_DAYS = 30
CHECKS_WINDOW_DAYS = 365      # за сколько дней ищем уже существующие данные


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Заполнить базу демо-данными (по вчерашний день включительно)."
    )
    parser.add_argument(
        "telegram_id", type=int,
        help="числовой Telegram ID пользователя (его показывает @userinfobot)",
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB,
        help=f"файл базы данных (по умолчанию {DEFAULT_DB})",
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help=f"сколько дней истории создать (по умолчанию {DEFAULT_DAYS})",
    )
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days должно быть не меньше 1")
    return args


def print_report(db: Database, user_id: int) -> None:
    checkins = db.get_checkins(user_id, DEFAULT_DAYS)
    impulses = db.get_impulses(user_id, DEFAULT_DAYS)
    if not checkins:
        print("За последние 30 дней записей нет.")
        return

    print("Средние:", averages(checkins))
    print("Топ триггеров:", top_triggers(impulses))
    print("Инсайты:")
    for text in build_insights(checkins, impulses) or ["(пока нет)"]:
        print(" -", text)

    last = checkins[-1]
    print("\nПлан по последнему check-in'у:")
    print(format_plan(build_plan(DEFAULT_TASKS, last.energy, last.stress)))


def main() -> None:
    args = parse_args()
    db = Database(args.db)
    try:
        db.init_schema()
        user_id = db.get_or_create_user(args.telegram_id)

        if db.get_checkins(user_id, CHECKS_WINDOW_DAYS):
            print(f"В {args.db} у этого пользователя уже есть данные. "
                  f"Удали файл {args.db} и запусти снова.\n")
        else:
            yesterday = date.today() - timedelta(days=1)
            seed(db, user_id, load_techniques(),
                 days=args.days, today=yesterday)
            print(f"Демо-данные созданы: {args.days} дн. по вчерашний день.\n")

        print_report(db, user_id)
    finally:
        db.close()


if __name__ == "__main__":
    main()