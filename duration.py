import re

MAX_MINUTES = 24 * 60
HOUR_UNITS = {"ч", "час", "часа", "часов", "h"}
MINUTE_UNITS = {"", "м", "мин", "минута", "минуты", "минут", "m"}

_PART = r"(\d+(?:\.\d+)?)\s*([а-яёa-z]*)\.?"
_WHOLE = re.compile(rf"(?:{_PART}\s*)+")
_CLOCK = re.compile(r"(\d+):([0-5]\d)")


def parse_duration(text: str) -> int:
    """Разбирает «45», «1.5 ч», «2 ч 30 мин», «1:30» и возвращает минуты.
    ValueError, если формат непонятен или значение вне 0..24 часов."""
    s = text.strip().lower().replace(",", ".")

    clock = _CLOCK.fullmatch(s)
    if clock:
        total = int(clock[1]) * 60 + int(clock[2])
    else:
        if not _WHOLE.fullmatch(s):
            raise ValueError("непонятный формат")
        seconds_free = 0.0
        seen = set()
        for number, unit in re.findall(_PART, s):
            if unit in HOUR_UNITS:
                kind, factor = "h", 60
            elif unit in MINUTE_UNITS:
                kind, factor = "m", 1
            else:
                raise ValueError(f"неизвестная единица: {unit}")
            if kind in seen:
                raise ValueError("единица указана дважды")
            if kind == "m" and "." in number:
                raise ValueError("минуты должны быть целыми")
            seen.add(kind)
            seconds_free += float(number) * factor
        total = round(seconds_free)

    if not 0 <= total <= MAX_MINUTES:
        raise ValueError("длительность вне диапазона 0..24 часа")
    return total