from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class User:
    id: int
    telegram_id: int
    problem: str = "phone"          # демо-привычка: залипание в телефоне
    wake_time: str = "07:00"


@dataclass
class CheckIn:
    date: date
    mood: int                       # 1-10
    energy: int                     # 1-10
    stress: int                     # 1-10
    episode: bool                   # был ли эпизод нежелательного поведения
    episode_minutes: int = 0


@dataclass
class Impulse:
    date: date
    trigger: str                    # "boredom" / "fatigue" / "stress" / "loneliness" / "idle"
    intensity: int                  # 1-5
    id: Optional[int] = None        # заполняется после записи в БД
    technique_id: Optional[str] = None   # None, пока техника не подобрана
    helped: Optional[bool] = None        # None, пока пользователь не ответил


@dataclass
class Task:
    title: str
    type: str                       # "must" / "growth" / "rest"
    load: int                       # вес нагрузки
    priority: int = 1


@dataclass
class Plan:
    selected: list[Task] = field(default_factory=list)
    dropped: list[Task] = field(default_factory=list)
    budget: int = 100
    used: int = 0
    level: str = "medium"           # "low" / "medium" / "high"
    overload: bool = False          # обязательные задачи не влезли в бюджет


@dataclass
class Technique:
    id: str
    title: str
    triggers: list[str]
    min_intensity: int
    max_intensity: int
    text: str