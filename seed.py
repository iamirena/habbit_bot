import random
from datetime import date, timedelta
from typing import Optional

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
    db = Database("habit_bot.db")
    db.init_schema()
    uid = db.get_or_create_user(757030906)

    if db.get_checkins(uid, 60):
        print("В demo.db уже есть данные. Удали файл demo.db и запусти снова.")
    else:
        yesterday = date.today() - timedelta(days=1)
        seed(db, uid, load_techniques(), today=yesterday)
        print("Демо-данные за 30 дней созданы.\n")

    checkins = db.get_checkins(uid, 30)
    impulses = db.get_impulses(uid, 30)

    print("Средние:", averages(checkins))
    print("Топ триггеров:", top_triggers(impulses))
    print("Инсайты:")
    for text in build_insights(checkins, impulses) or ["(пока нет)"]:
        print(" -", text)

    last = checkins[-1]
    print("\nПлан по последнему check-in'у:")
    print(format_plan(build_plan(DEFAULT_TASKS, last.energy, last.stress)))
    db.close()