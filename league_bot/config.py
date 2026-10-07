"""Configuration: .env parsing and typed settings (stdlib only)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Mapping, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_LAUNCH_URI = "googleplaygames://launch/?id=com.gear2.growslayer&lid=1&pid=1"


class ConfigError(ValueError):
    """An invalid or missing setting in the environment / .env file."""


def parse_env_file(path: Path) -> Dict[str, str]:
    """Parse KEY=VALUE lines. Only whole-line comments are supported."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    values: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _as_bool(key: str, value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} must be 1/0 (got {value!r})")


def _as_int(key: str, value: str, minimum: int = 0) -> int:
    try:
        number = int(value.strip())
    except ValueError:
        raise ConfigError(f"{key} must be an integer (got {value!r})") from None
    if number < minimum:
        raise ConfigError(f"{key} must be >= {minimum}")
    return number


def _as_user_ids(value: str) -> FrozenSet[int]:
    ids = set()
    for part in value.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            raise ConfigError("ALLOWED_USER_IDS must be comma-separated numeric Telegram user ids") from None
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    telegram_token: str = ""
    allowed_user_ids: FrozenSet[int] = frozenset()
    window_title: str = ""
    launch_uri: str = DEFAULT_LAUNCH_URI
    play_games_exe: str = ""
    process_names: Tuple[str, ...] = ("client.exe", "crosvm.exe")
    start_macro: str = "start_game"
    macros_dir: Path = REPO_ROOT / "macros"
    data_dir: Path = REPO_ROOT / "state"  # the daily list and other local state
    foreground_input: bool = False
    max_command_age: int = 300
    log_file: str = ""

    def require_token(self) -> str:
        if not self.telegram_token:
            raise ConfigError("TELEGRAM_TOKEN is not set (see .env.example)")
        return self.telegram_token

    def summary(self) -> Dict[str, str]:
        """Human-readable view for `check`; never includes the token itself."""
        return {
            "TELEGRAM_TOKEN": "set" if self.telegram_token else "MISSING",
            "ALLOWED_USER_IDS": ",".join(str(i) for i in sorted(self.allowed_user_ids)) or "(empty: nobody authorized)",
            "SLAYER_WINDOW_TITLE": self.window_title or "MISSING",
            "SLAYER_LAUNCH_URI": self.launch_uri or "(unset)",
            "SLAYER_PLAY_GAMES_EXE": self.play_games_exe or "(unset)",
            "SLAYER_PROCESS_NAMES": ",".join(self.process_names),
            "SLAYER_START_MACRO": self.start_macro,
            "SLAYER_MACROS_DIR": str(self.macros_dir),
            "SLAYER_DATA_DIR": str(self.data_dir),
            "SLAYER_FOREGROUND_INPUT": "1" if self.foreground_input else "0",
            "SLAYER_MAX_COMMAND_AGE": str(self.max_command_age),
        }


def load_settings(environ: Optional[Mapping[str, str]] = None, env_file: Optional[Path] = DEFAULT_ENV_FILE) -> Settings:
    """Build Settings from the .env file, overridden by real environment variables."""
    merged: Dict[str, str] = {}
    if env_file is not None:
        merged.update(parse_env_file(Path(env_file)))
    merged.update(os.environ if environ is None else environ)

    def get(key: str, default: str = "") -> str:
        return merged.get(key, default).strip()

    token = get("TELEGRAM_TOKEN")
    if token and ":" not in token:
        raise ConfigError("TELEGRAM_TOKEN has an invalid format (expected '<digits>:<secret>')")

    names = tuple(n.strip() for n in get("SLAYER_PROCESS_NAMES", "client.exe,crosvm.exe").split(",") if n.strip())
    macro = get("SLAYER_START_MACRO", "start_game")
    if not macro.replace("_", "").replace("-", "").isalnum():
        raise ConfigError("SLAYER_START_MACRO may only contain letters, digits, '_' and '-'")

    defaults = Settings()
    return Settings(
        telegram_token=token,
        allowed_user_ids=_as_user_ids(get("ALLOWED_USER_IDS")),
        window_title=get("SLAYER_WINDOW_TITLE"),
        launch_uri=get("SLAYER_LAUNCH_URI", defaults.launch_uri),
        play_games_exe=get("SLAYER_PLAY_GAMES_EXE"),
        process_names=names or defaults.process_names,
        start_macro=macro,
        macros_dir=Path(get("SLAYER_MACROS_DIR")) if get("SLAYER_MACROS_DIR") else defaults.macros_dir,
        data_dir=Path(get("SLAYER_DATA_DIR")) if get("SLAYER_DATA_DIR") else defaults.data_dir,
        foreground_input=_as_bool("SLAYER_FOREGROUND_INPUT", get("SLAYER_FOREGROUND_INPUT", "0")),
        max_command_age=_as_int("SLAYER_MAX_COMMAND_AGE", get("SLAYER_MAX_COMMAND_AGE", "300")),
        log_file=get("SLAYER_LOG_FILE"),
    )
