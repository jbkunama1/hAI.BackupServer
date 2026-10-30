"""Zentrale Eingabevalidierung (ohne Framework-Abhaengigkeiten)."""
import posixpath
import re

HOST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
HOST_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DB_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$-]{0,62}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,64}$")
FINGERPRINT_RE = re.compile(r"^[a-f0-9]{16,64}$")
CRON_RE = re.compile(r"^[0-9*/,\-]+( [0-9*/,\-]+){4}$")
LABEL_RE = re.compile(r"^[A-Za-z0-9_.\- ]{1,128}$")
FSTYPES_RE = re.compile(r"^[A-Za-z0-9_. +-]{0,100}$")
# Einzelner Verzeichnisname unterhalb des NAS-Basispfads ("." = direkt im Basispfad, Altlayout).
DIR_NAME_RE = re.compile(r"(?:[.]|[A-Za-z0-9][A-Za-z0-9_.-]{0,62})")
DEFAULT_BACKUP_DIR = "Server"

FORBIDDEN_EXACT = {
    "/", "/etc", "/root", "/boot", "/run", "/var", "/var/run", "/usr", "/bin",
    "/sbin", "/lib", "/lib64", "/home", "/proc", "/sys", "/dev",
}
FORBIDDEN_TOP = {"proc", "sys", "dev"}


class ValidationError(ValueError):
    """Ungueltige Benutzereingabe."""


def _match(rx, value, label):
    if not isinstance(value, str) or not rx.match(value):
        raise ValidationError(f"Ungueltiger Wert fuer {label}")
    return value


def host_id(v):
    return _match(HOST_ID_RE, v, "Host-ID (erlaubt: A-Z a-z 0-9 _ -, max. 32 Zeichen)")


def host_name(v):
    return _match(HOST_NAME_RE, v, "Hostname")


def container_name(v):
    return _match(CONTAINER_RE, v, "Containername")


def db_user(v):
    return _match(DB_USER_RE, v, "DB-Benutzer")


def run_id(v):
    return _match(RUN_ID_RE, v, "run_id")


def fingerprint(v):
    return _match(FINGERPRINT_RE, v, "fingerprint")


def label(v):
    return _match(LABEL_RE, v, "Bezeichnung")


def dir_name(v):
    """Ein einzelner Verzeichnisname (kein Pfad): alphanumerischer Beginn, kein '..', kein '/'.

    Ausnahme: genau "." legt Backups direkt unter dem NAS-Basispfad ab (Altlayout).
    """
    if not isinstance(v, str) or not DIR_NAME_RE.fullmatch(v) or ".." in v:
        raise ValidationError("Ungueltiger Wert fuer Backup-Verzeichnisname "
                              "(erlaubt: A-Z a-z 0-9 _ . -, max. 63 Zeichen, kein '..' oder '/')")
    return v


def cron_schedule(v):
    return _match(CRON_RE, v, "Cron-Ausdruck (5 Felder)")


def fstypes(v):
    return _match(FSTYPES_RE, v or "", "Dateisystemtypen")


def path(p):
    """Absoluter, normalisierter, unkritischer Pfad - sonst ValidationError."""
    if (not isinstance(p, str) or not p.startswith("/") or len(p) > 4096
            or any(c in p for c in "\x00\r\n")):
        raise ValidationError("Pfad muss absolut sein und darf keine Steuerzeichen enthalten")
    if ".." in p.split("/"):
        raise ValidationError("Pfad darf kein '..' enthalten")
    n = posixpath.normpath(p)
    if n.startswith("//"):
        n = "/" + n.lstrip("/")
    top = n.split("/")[1] if n != "/" else ""
    if n in FORBIDDEN_EXACT or n.endswith("docker.sock") or top in FORBIDDEN_TOP:
        raise ValidationError(f"Pfad nicht erlaubt: {n}")
    return n


def number(v, label_, lo, hi, default=None):
    if v in (None, ""):
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValidationError(f"{label_} muss eine Zahl sein")
    if not (lo <= f <= hi):
        raise ValidationError(f"{label_} muss zwischen {lo} und {hi} liegen")
    return f


def slug(name):
    s = re.sub(r"[^a-z0-9_-]+", "-", str(name).lower()).strip("-")
    return (s or "host")[:28]
