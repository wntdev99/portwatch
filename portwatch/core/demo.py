"""README 스크린샷과 UI 점검에 쓰는 가상 데이터."""
from .collect import classify, can_kill

DEMO_ROWS = [
    (3000, "127.0.0.1", "node", "storefront · Next.js",
     "node node_modules/.bin/next dev --port 3000", "~/work/storefront", "http", False, "02:41:08"),
    (5173, "127.0.0.1", "node", "admin-console · Vite",
     "node node_modules/.bin/vite --host 127.0.0.1 --port 5173", "~/work/admin-console", "http", False, "01:12:55"),
    (8000, "0.0.0.0", "python3", "billing-api · uvicorn",
     "uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload", "~/work/billing-api", "http", False, "03:27:19"),
    (6006, "127.0.0.1", "node", "design-system · Storybook",
     "node node_modules/.bin/storybook dev -p 6006", "~/work/design-system", "http", False, "00:48:02"),
    (5432, "127.0.0.1", "postgres", "pg-main · Docker",
     "postgres -c config_file=/etc/postgresql/postgresql.conf", "/var/lib/postgresql", "tcp", True, "11:04:33"),
    (6379, "0.0.0.0", "redis-server", "cache · Docker",
     "redis-server *:6379", "/data", "tcp", True, "11:04:33"),
    (9090, "127.0.0.1", "prometheus", "prometheus · Docker",
     "/bin/prometheus --config.file=/etc/prometheus/prometheus.yml", "/prometheus", "http", True, "11:04:30"),
    (22, "0.0.0.0", "sshd", "SSH (추정)", "", "", "tcp", False, ""),
    (631, "127.0.0.1", "cupsd", "CUPS 인쇄 (추정)", "", "", "http", False, ""),
]


def demo_rows():
    from .probe import url_for
    rows = []
    for port, addr, name, title, cmd, cwd, kind, docker, uptime in DEMO_ROWS:
        row = {
            "port": port, "addr": addr, "addrs": addr, "name": name, "pid": 1000 + port,
            "user": "demo", "cmdline": cmd, "cwd": cwd, "docker": docker,
            "uptime": uptime, "restricted": not cmd, "container": None,
            "kind": kind, "title": title,
            "health": (200, 3) if kind == "http" else None,
            "public": addr in ("0.0.0.0", "::"),
        }
        row["section"] = classify(row)
        row["can_kill"] = not docker and bool(cmd)
        row["url"] = url_for(row) if kind in ("http", "https") else None
        rows.append(row)
    return rows
