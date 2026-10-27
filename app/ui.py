"""Jinja-Filter fuer die Weboberflaeche."""


def human_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def fmt_ts(s):
    return str(s).replace("T", " ").replace("Z", " UTC") if s else "-"


def fmt_dur(sec):
    try:
        sec = int(float(sec))
    except (TypeError, ValueError):
        return "-"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h} h {m} min" if h else (f"{m} min {s} s" if m else f"{s} s")


def register(env):
    env.filters.update(human_size=human_size, fmt_ts=fmt_ts, fmt_dur=fmt_dur)
