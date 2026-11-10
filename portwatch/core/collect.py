"""소켓 목록을 사람이 읽을 수 있는 행으로 바꾼다."""
import json
import os
import re

from . import platform as plat
from . import probe

SYSTEM_PORTS = {22, 53, 631, 5353, 41641, 5355, 137, 138, 139, 445}
SYSTEM_PROCS = {"sshd", "cupsd", "systemd-resolve", "tailscaled", "avahi-daemon",
                "jumpcloud-agent", "jumpcloud-assist-service", "rustdesk", "glances",
                "launchd", "mDNSResponder", "svchost.exe", "System"}

WELL_KNOWN = {
    22: "SSH", 53: "DNS", 80: "HTTP", 443: "HTTPS", 445: "SMB", 631: "CUPS 인쇄",
    1883: "MQTT", 3000: "개발 서버", 3306: "MySQL", 3389: "원격 데스크톱",
    5000: "개발 서버", 5432: "PostgreSQL", 5433: "PostgreSQL", 5672: "RabbitMQ",
    5900: "VNC", 6379: "Redis", 7070: "원격 관리", 8000: "개발 서버",
    8080: "HTTP 대체", 8443: "HTTPS 대체", 9000: "개발 서버", 9090: "Prometheus",
    11211: "Memcached", 27017: "MongoDB", 61209: "Glances",
}

RISKY_PORTS = {
    6379: "Redis", 5432: "PostgreSQL", 3306: "MySQL", 27017: "MongoDB",
    11211: "Memcached", 9200: "Elasticsearch", 5672: "RabbitMQ",
    2375: "Docker API", 9000: "관리 콘솔", 8086: "InfluxDB",
}

CURRENT_USER = plat.current_user()
_name_cache = {}


def ssh_tunnel(cmd):
    """ssh -L 포워딩에서 '내 포트 → 원격' 설명을 만든다."""
    m = re.search(r"-L\s*(?:(\S+?):)?(\d+):(\S+?):(\d+)", cmd)
    if not m:
        return None
    _, local, host, remote = m.groups()
    target = re.search(r"(?:^|\s)([\w.-]+@[\w.-]+|[\w.-]+)\s*$", cmd.strip())
    via = f" ({target.group(1)} 경유)" if target else ""
    return f"{local} → {host}:{remote}{via}"


def friendly_name(row):
    key = (row["pid"], row["port"])
    if key in _name_cache:
        return _name_cache[key]

    cmd, cwd, name = row["cmdline"], row["cwd"], row["name"]
    label = row.get("container")

    if not label and cwd and os.path.isdir(cwd):
        pkg = os.path.join(cwd, "package.json")
        if os.path.isfile(pkg):
            try:
                with open(pkg, encoding="utf-8") as fh:
                    label = json.load(fh).get("name")
            except Exception:
                pass

    if not label:
        m = re.search(r"--directory\s+(\S+)", cmd)
        if m:
            label = os.path.basename(m.group(1).rstrip("/\\")) or None

    if not label and cwd and cwd not in ("/", os.path.expanduser("~")):
        label = os.path.basename(cwd.rstrip("/\\")) or None

    if not label:
        label = name or f"포트 {row['port']}"

    tunnel = ssh_tunnel(cmd) if name in ("ssh", "ssh.exe") else None
    if tunnel:
        _name_cache[key] = f"SSH 터널 · {tunnel}"
        return _name_cache[key]

    runtime = ""
    if "vite" in cmd:
        runtime = "Vite"
    elif "uvicorn" in cmd:
        runtime = "uvicorn"
    elif "http.server" in cmd:
        runtime = "http.server"
    elif name in ("node", "bun", "python3", "python", "python.exe", "deno", "node.exe"):
        runtime = name
    elif row["docker"]:
        runtime = "Docker"

    text = f"{label} · {runtime}" if runtime and runtime.lower() != str(label).lower() else label
    _name_cache[key] = text
    return text


def classify(row):
    if row["restricted"] or row["name"] in SYSTEM_PROCS or row["port"] in SYSTEM_PORTS:
        return "system"
    if row["docker"]:
        return "docker"
    return "mine"


def can_kill(row):
    """내가 소유한, 컨테이너 밖의 프로세스만 종료 대상으로 본다."""
    return (bool(row["pid"]) and not row["restricted"]
            and not row["docker"] and row["user"] == CURRENT_USER)


def merge_dual_stack(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row["port"], row["pid"], row["name"]), []).append(row)
    merged = []
    for group in groups.values():
        base = dict(group[0])
        addrs = sorted({r["addr"] for r in group})
        wildcard = [a for a in addrs if a in ("0.0.0.0", "::", "*")]
        base["addr"] = wildcard[0] if wildcard else addrs[0]
        base["addrs"] = ", ".join(addrs)
        base["public"] = bool(wildcard) or any(
            not a.startswith("127.") and a != "::1" for a in addrs)
        merged.append(base)
    return sorted(merged, key=lambda r: (r["port"], r["addr"]))


def collect(check_health=False):
    """화면에 바로 쓸 수 있는 행 목록을 돌려준다."""
    if os.environ.get("PORTWATCH_DEMO"):
        from .demo import demo_rows
        return demo_rows()

    rows = plat.listeners()
    for row in rows:
        if row["pid"]:
            row.update(plat.process_info(row["pid"]))
            row["container"] = plat.container_of(row["pid"]) if row["docker"] else None
            row["restricted"] = not row["cmdline"] and row["user"] in ("?", "")
        else:
            row.update({"user": "root", "cmdline": "", "cwd": "", "container": None,
                        "docker": False, "uptime": "", "restricted": True})

    merged = merge_dual_stack(rows)
    for row in merged:
        row["kind"] = probe.kind(row["addr"], row["port"])
        row["health"] = (probe.health(row["addr"], row["port"])
                         if check_health and row["kind"] == "http" else None)
        if row["restricted"]:
            guess = WELL_KNOWN.get(row["port"])
            row["title"] = f"{guess} (추정)" if guess else f"포트 {row['port']}"
        else:
            row["title"] = friendly_name(row)
        row["section"] = classify(row)
        row["can_kill"] = can_kill(row)
        row["url"] = probe.url_for(row) if row["kind"] in ("http", "https") else None
    return merged
