from typing import Optional

from models import Plan, Task

BASE_BUDGET = 100
MIN_BUDGET = 40

# Шаблонные задачи дня (отдельной таблицы задач в MVP нет)
DEFAULT_TASKS = [
    Task("Работа / учёба", "must", load=50, priority=5),
    Task("Подготовка к собеседованию", "growth", load=20, priority=3),
    Task("Чтение", "growth", load=10, priority=2),
    Task("Тренировка", "growth", load=30, priority=2),
    Task("Отдых без экрана", "rest", load=0, priority=1),
]

LEVEL_NAMES = {"low": "лёгкий", "medium": "средний", "high": "высокий"}


def calc_budget(energy: Optional[int], stress: Optional[int]) -> int:
    """Бюджет нагрузки на день по вчерашнему состоянию.
    Если данных нет (None), берём базовый бюджет."""
    if energy is None or stress is None:
        return BASE_BUDGET
    budget = (BASE_BUDGET
              - 5 * max(0, 6 - energy)
              - 3 * max(0, stress - 5))
    return max(MIN_BUDGET, budget)


def _level(used: int, budget: int, overload: bool) -> str:
    ratio = used / budget
    if overload or ratio >= 0.8:
        return "high"
    if ratio >= 0.5:
        return "medium"
    return "low"


def build_plan(tasks: list[Task], energy: Optional[int],
               stress: Optional[int]) -> Plan:
    budget = calc_budget(energy, stress)

    must = [t for t in tasks if t.type == "must"]
    rest = [t for t in tasks if t.type == "rest"]
    growth = [t for t in tasks if t.type == "growth"]

    used = sum(t.load for t in must)
    overload = used > budget          # обязательное не влезло, но не скрываем

    growth.sort(key=lambda t: t.priority / max(t.load, 1), reverse=True)
    chosen_growth, dropped = [], []
    for t in growth:
        if used + t.load <= budget:
            chosen_growth.append(t)
            used += t.load
        else:
            dropped.append(t)

    return Plan(
        selected=must + chosen_growth + rest,
        dropped=dropped,
        budget=budget,
        used=used,
        level=_level(used, budget, overload),
        overload=overload,
    )


def format_plan(plan: Plan) -> str:
    lines = [f"План на сегодня. Нагрузка: {LEVEL_NAMES[plan.level]} "
             f"({plan.used} из {plan.budget})", ""]
    lines += [f"• {t.title}" for t in plan.selected]
    if plan.dropped:
        names = ", ".join(t.title for t in plan.dropped)
        lines += ["", f"Не вошло в план (не хватает бюджета нагрузки): {names}."]
    if plan.overload:
        lines += ["", "Обязательные дела превышают сегодняшний бюджет, "
                      "постарайся не добавлять ничего сверх плана."]
    return "\n".join(lines)