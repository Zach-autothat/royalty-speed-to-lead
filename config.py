"""Tiny .env loader + config — no third-party dependencies."""
import os


def load_env(path=None):
    """Load KEY=VALUE lines from a .env file into os.environ (without overwriting
    anything already set in the real environment)."""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


load_env()


def cfg(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required config: {name}")
    return val


# Convenience accessors
TOKEN = cfg("GHL_TOKEN", required=True)
LOCATION_ID = cfg("GHL_LOCATION_ID", required=True)
API_VERSION = cfg("GHL_API_VERSION", "2021-07-28")

BH_TIMEZONE = cfg("BH_TIMEZONE", "America/Chicago")
BH_OPEN = cfg("BH_OPEN", "08:00")
BH_CLOSE = cfg("BH_CLOSE", "18:00")
BH_WORKDAYS = [int(x) for x in cfg("BH_WORKDAYS", "0,1,2,3,4,5,6").split(",") if x != ""]
