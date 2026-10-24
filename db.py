import sqlite3
from datetime import date, timedelta
from typing import Optional

from models import CheckIn, Impulse

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,
    problem     TEXT NOT NULL DEFAULT 'phone',
    wake_time   TEXT NOT NULL DEFAULT '07:00'
);

CREATE TABLE IF NOT EXISTS checkins (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    date            TEXT NOT NULL,                      -- ISO: 2026-10-17
    mood            INTEGER NOT NULL CHECK (mood BETWEEN 1 AND 10),
    energy          INTEGER NOT NULL CHECK (energy BETWEEN 1 AND 10),
    stress          INTEGER NOT NULL CHECK (stress BETWEEN 1 AND 10),
    episode         INTEGER NOT NULL CHECK (episode IN (0, 1)),
    episode_minutes INTEGER NOT NULL DEFAULT 0 CHECK (episode_minutes >= 0),
    UNIQUE (user_id, date)                              -- один check-in в день
);

CREATE TABLE IF NOT EXISTS impulses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    date         TEXT NOT NULL,
    trigger      TEXT NOT NULL,
    intensity    INTEGER NOT NULL CHECK (intensity BETWEEN 1 AND 5),
    technique_id TEXT,                                  -- NULL, пока не подобрана
    helped       INTEGER CHECK (helped IN (0, 1))       -- NULL, пока нет оценки
);
"""
def _since_iso(days: int, today: Optional[date]) -> str:
    """Первая дата окна [today-(days-1), today] в ISO-формате."""
    if days < 1:
        raise ValueError("days должно быть не меньше 1")
    today = today or date.today()
    return (today - timedelta(days=days - 1)).isoformat()

class Database:
    def __init__(self, path: str = "habit_bot.db"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.conn.close()

    # ---------- схема ----------
    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- users ----------
    def get_or_create_user(self, telegram_id: int) -> int:
        row = self.conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO users (telegram_id) VALUES (?)", (telegram_id,)
        )
        self.conn.commit()
        return cur.lastrowid

    # ---------- checkins ----------
    def add_checkin(self, user_id: int, c: CheckIn) -> None:
        """Если check-in за эту дату уже есть, он перезаписывается."""
        self.conn.execute(
            """
            INSERT INTO checkins
                (user_id, date, mood, energy, stress, episode, episode_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, date) DO UPDATE SET
                mood = excluded.mood,
                energy = excluded.energy,
                stress = excluded.stress,
                episode = excluded.episode,
                episode_minutes = excluded.episode_minutes
            """,
            (user_id, c.date.isoformat(), c.mood, c.energy, c.stress,
             int(c.episode), c.episode_minutes),
        )
        self.conn.commit()

    def get_checkins(self, user_id: int, days: int,
                     today: Optional[date] = None) -> list[CheckIn]:
        """Check-in'ы за последние `days` дней, от старых к новым."""
        since = _since_iso(days, today)
        rows = self.conn.execute(
            """
            SELECT date, mood, energy, stress, episode, episode_minutes
            FROM checkins
            WHERE user_id = ? AND date >= ?
            ORDER BY date
            """,
            (user_id, since),
        ).fetchall()
        return [
            CheckIn(
                date=date.fromisoformat(r["date"]),
                mood=r["mood"], energy=r["energy"], stress=r["stress"],
                episode=bool(r["episode"]),
                episode_minutes=r["episode_minutes"],
            )
            for r in rows
        ]

    # ---------- impulses ----------
    def add_impulse(self, user_id: int, imp: Impulse) -> int:
        """Шаг 1: сохраняем импульс без техники и без оценки."""
        cur = self.conn.execute(
            "INSERT INTO impulses (user_id, date, trigger, intensity) "
            "VALUES (?, ?, ?, ?)",
            (user_id, imp.date.isoformat(), imp.trigger, imp.intensity),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_technique(self, impulse_id: int, technique_id: str) -> None:
        """Шаг 2: записываем, какую технику предложили."""
        self.conn.execute(
            "UPDATE impulses SET technique_id = ? WHERE id = ?",
            (technique_id, impulse_id),
        )
        self.conn.commit()

    def set_helped(self, impulse_id: int, helped: bool) -> None:
        """Шаг 3: оценка пользователя «помогло / нет»."""
        cur = self.conn.execute(
            "UPDATE impulses SET helped = ? WHERE id = ?",
            (int(helped), impulse_id),
        )
        self.conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"Импульс {impulse_id} не найден")

    def get_impulses(self, user_id: int, days: int,
                     today: Optional[date] = None) -> list[Impulse]:
        since = _since_iso(days, today)
        rows = self.conn.execute(
            """
            SELECT id, date, trigger, intensity, technique_id, helped
            FROM impulses
            WHERE user_id = ? AND date >= ?
            ORDER BY id
            """,
            (user_id, since),
        ).fetchall()
        return [
            Impulse(
                id=r["id"],
                date=date.fromisoformat(r["date"]),
                trigger=r["trigger"],
                intensity=r["intensity"],
                technique_id=r["technique_id"],
                helped=None if r["helped"] is None else bool(r["helped"]),
            )
            for r in rows
        ]