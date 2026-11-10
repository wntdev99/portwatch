"""설정 파일. OS 별 표준 위치를 따른다."""
import json
import os
import sys


def config_path():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "PortWatch", "config.json")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/PortWatch/config.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    legacy = os.path.expanduser("~/.config/portwatch.json")
    if os.path.exists(legacy):
        return legacy                       # 이전 버전에서 쓰던 자리를 그대로 쓴다
    return os.path.join(base, "portwatch", "config.json")


DEFAULTS = {
    "pinned": [],
    "show_system": False,
    "auto_refresh": True,
    "check_health": False,
    "notify_changes": True,
    "commands": {},
}


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(config_path(), encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except Exception:
        pass
    return cfg


def save(cfg):
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass
