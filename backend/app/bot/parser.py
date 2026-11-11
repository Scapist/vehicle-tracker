"""Pure mileage-message parsing and vehicle guessing. No DB, no Telegram."""
import re
from dataclasses import dataclass

MAX_KM = 1_500_000
SPACES = "   "
# a number: digits with optional grouping/decimal separators, optionally followed by 'k'
NUM_RE = re.compile(r"\d[\d .,]*\d(?:\s*k\b)?|\d(?:\s*k\b)?", re.IGNORECASE)
GROUPED = re.compile(r"^\d{1,3}(?:([ ,.])\d{3})+$")


@dataclass(frozen=True)
class Parsed:
    km: int | None = None
    nickname: str | None = None
    error: str | None = None


def parse_number(raw: str) -> int | None:
    s = raw.strip().lower()
    for ch in SPACES:
        s = s.replace(ch, " ")
    k = s.endswith("k")
    if k:
        s = s[:-1].strip()
        if re.fullmatch(r"\d+([.,]\d{1,3})?", s):
            return round(float(s.replace(",", ".")) * 1000)
        return None
    if re.fullmatch(r"\d+", s):
        return int(s)
    g = GROUPED.match(s)
    if g and len({c for c in s if c in " ,."}) == 1:
        return int(re.sub(r"\D", "", s))
    return None  # e.g. "84.5" or "84,5": decimal or thousands? don't guess


def parse_mileage(text: str, nicknames: list[str]) -> Parsed:
    t = text.strip()
    for ch in SPACES:
        t = t.replace(ch, " ")
    matches = list(NUM_RE.finditer(t))
    if len(matches) != 1:
        return Parsed(error="I couldn't find a single mileage number. Try `84500` or `84,500 km`.")
    m = matches[0]
    km = parse_number(m.group())
    if km is None:
        return Parsed(error=f"'{m.group().strip()}' is ambiguous. Write it as 84500, 84,500 or 84.5k.")
    if km < 1 or km > MAX_KM:
        return Parsed(error=f"{km:,} km doesn't look like a real odometer reading.")
    rest = (t[:m.start()] + " " + t[m.end():]).lower()
    rest = re.sub(r"\b(kms?|kilometers?|kilometres?|odo|odometer)\b", " ", rest)
    rest = re.sub(r"[^\w\s'-]", " ", rest).strip()
    rest = re.sub(r"\s+", " ", rest)
    if not rest:
        return Parsed(km=km)
    exact = [n for n in nicknames if n.lower() == rest]
    if exact:
        return Parsed(km=km, nickname=exact[0])
    prefix = [n for n in nicknames if n.lower().startswith(rest)]
    if len(prefix) == 1:
        return Parsed(km=km, nickname=prefix[0])
    return Parsed(error=f"I don't know a vehicle called '{rest}'. Known: {', '.join(nicknames) or 'none'}.")


def guess_vehicle(km: int, vehicles: list[tuple[int, int | None]], window: int = 30_000) -> int | None:
    """vehicles: (id, current_km). Closest current km at or below `km`, within `window`.
    A lone vehicle is always the guess."""
    if len(vehicles) == 1:
        return vehicles[0][0]
    below = [(km - cur, vid) for vid, cur in vehicles if cur is not None and cur <= km]
    below = [b for b in below if b[0] <= window]
    if not below:
        return None
    best = sorted(below)
    if len(best) > 1 and best[0][0] == best[1][0]:
        return None
    return best[0][1]
