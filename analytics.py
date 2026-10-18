import statistics
from collections import Counter
from typing import Callable, Optional

from models import CheckIn, Impulse

MIN_DAYS_INSIGHTS = 7     # меньше дней: инсайтов нет
MIN_OBS_CORR = 10         # меньше наблюдений: корреляцию не считаем
MIN_GROUP_DAYS = 3        # минимум дней в группе «высокий стресс / низкая энергия»
CORR_THRESHOLD = 0.5      # связь считаем заметной при |r| >= 0.5
RATE_DIFF = 0.2           # разница долей эпизодов, чтобы вывести инсайт
HIGH_STRESS = 7
LOW_ENERGY = 4


def averages(checkins: list[CheckIn]) -> Optional[dict]:
    """Средние показатели. Минуты считаем только по дням с эпизодом."""
    if not checkins:
        return None
    episode_days = [c for c in checkins if c.episode]
    return {
        "days": len(checkins),
        "mood": statistics.mean(c.mood for c in checkins),
        "energy": statistics.mean(c.energy for c in checkins),
        "stress": statistics.mean(c.stress for c in checkins),
        "episode_days": len(episode_days),
        "avg_episode_minutes": (
            statistics.mean(c.episode_minutes for c in episode_days)
            if episode_days else None
        ),
    }


def top_triggers(impulses: list[Impulse], n: int = 3) -> list[tuple[str, int]]:
    return Counter(i.trigger for i in impulses).most_common(n)


def safe_correlation(xs: list[float], ys: list[float],
                     min_obs: int = MIN_OBS_CORR) -> Optional[float]:
    """Корреляция Пирсона или None, если данных мало или ряд константный."""
    if len(xs) != len(ys) or len(xs) < min_obs:
        return None
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    return statistics.correlation(xs, ys)


def episode_rate(checkins: list[CheckIn],
                 condition: Callable[[CheckIn], bool]) -> Optional[float]:
    """Доля дней с эпизодом среди дней, где выполняется condition.
    None, если таких дней нет."""
    subset = [c for c in checkins if condition(c)]
    if not subset:
        return None
    return sum(1 for c in subset if c.episode) / len(subset)


def _corr_text(label: str, r: float) -> str:
    direction = "выше" if r > 0 else "ниже"
    return (f"Наблюдается связь (r = {r:.2f}): в дни, когда {label} {direction}, "
            f"эпизоды длиннее. Это не доказывает причину.")


def _rate_insight(checkins, base, label, condition) -> Optional[str]:
    group = [c for c in checkins if condition(c)]
    if len(group) < MIN_GROUP_DAYS:
        return None
    rate = episode_rate(checkins, condition)
    if rate - base >= RATE_DIFF:
        return (f"{label}: эпизоды случались в {rate:.0%} таких дней "
                f"(в среднем {base:.0%}).")
    return None


def build_insights(checkins: list[CheckIn],
                   impulses: list[Impulse]) -> list[str]:
    """Готовые фразы-закономерности. Пустой список, если данных мало
    или заметных закономерностей нет."""
    if len(checkins) < MIN_DAYS_INSIGHTS:
        return []

    insights = []
    base = episode_rate(checkins, lambda c: True)

    for label, cond in [
        ("В дни с высоким стрессом", lambda c: c.stress >= HIGH_STRESS),
        ("В дни с низкой энергией", lambda c: c.energy <= LOW_ENERGY),
    ]:
        text = _rate_insight(checkins, base, label, cond)
        if text:
            insights.append(text)

    minutes = [c.episode_minutes for c in checkins]
    for label, values in [
        ("энергия", [c.energy for c in checkins]),
        ("стресс", [c.stress for c in checkins]),
    ]:
        r = safe_correlation(values, minutes)
        if r is not None and abs(r) >= CORR_THRESHOLD:
            insights.append(_corr_text(label, r))

    return insights