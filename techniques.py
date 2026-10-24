import json
import random
from typing import Optional
from pathlib import Path

from models import Impulse, Technique

EPSILON = 0.2   # доля случайных выборов, чтобы у "просевших" техник был шанс


class TechniquesError(Exception):
    """Файл техник не найден, повреждён или имеет неверный формат."""


def load_techniques(path: str | Path | None = None) -> list[Technique]:
    if path is None:
        path = Path(__file__).with_name("techniques.json")

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError as e:
        raise TechniquesError(f"Файл техник не найден: {path}") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise TechniquesError(f"Файл техник повреждён: {path} ({e})") from e
    except OSError as e:
        raise TechniquesError(f"Не удалось прочитать файл техник {path}: {e}") from e

    if not isinstance(raw, list):
        raise TechniquesError(f"{path}: ожидается список техник")
    try:
        return [Technique(**item) for item in raw]
    except TypeError as e:
        raise TechniquesError(f"{path}: неверный формат техники ({e})") from e


def helped_rate(technique_id: str, impulses: list[Impulse]) -> float:
    """Сглаженная доля «помогло» (сглаживание Лапласа).
    Считаются только оценённые импульсы (helped is not None).
    Без оценок получается 0.5, одна неудача не обнуляет технику."""
    rated = [i for i in impulses
             if i.technique_id == technique_id and i.helped is not None]
    helped = sum(1 for i in rated if i.helped)
    return (helped + 1) / (len(rated) + 2)


def pick_technique(techs: list[Technique], trigger: str, intensity: int,
                   impulses: list[Impulse],
                   rng: Optional[random.Random] = None,
                   epsilon: float = EPSILON) -> Optional[Technique]:
    """Фильтр по триггеру и интенсивности, затем:
    - с вероятностью epsilon берём случайную из подходящих (исследование);
    - иначе берём лучшую по helped_rate, при равенстве случайную из лучших."""
    rng = rng or random
    candidates = [
        t for t in techs
        if trigger in t.triggers and t.min_intensity <= intensity <= t.max_intensity
    ]
    if not candidates:
        return None
    if rng.random() < epsilon:
        return rng.choice(candidates)
    rates = {t.id: helped_rate(t.id, impulses) for t in candidates}
    best = max(rates.values())
    top = [t for t in candidates if rates[t.id] == best]
    return rng.choice(top)