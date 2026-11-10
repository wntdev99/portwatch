"""포트가 무엇을 말하는지 알아보고, HTTP 라면 상태까지 확인한다."""
import re
import socket
import time

PROBE_TIMEOUT = 0.35
HEALTH_TIMEOUT = 1.0

_kind_cache = {}


def connect_host(addr):
    return "127.0.0.1" if addr in ("0.0.0.0", "*", "::", "") else addr


def _open(host, port, timeout):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((host, port))
    return sock


def kind(addr, port):
    """'http' | 'https' | 'tcp'. 포트마다 한 번만 재고 캐시한다."""
    key = (addr, port)
    if key in _kind_cache:
        return _kind_cache[key]
    host = connect_host(addr)
    result = "tcp"
    try:
        with _open(host, port, PROBE_TIMEOUT) as sock:
            sock.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
            head = sock.recv(16)
            if head.startswith(b"HTTP/"):
                result = "http"
            elif head[:1] in (b"\x15", b"\x16"):
                result = "https"
    except (socket.timeout, ConnectionResetError):
        result = "https" if port in (443, 8443) else "tcp"
    except Exception:
        result = "tcp"
    _kind_cache[key] = result
    return result


def health(addr, port):
    """(상태 코드, 왕복 ms) 또는 None."""
    host = connect_host(addr)
    try:
        start = time.monotonic()
        with _open(host, port, HEALTH_TIMEOUT) as sock:
            sock.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n"
                         b"User-Agent: PortWatch\r\nConnection: close\r\n\r\n")
            head = sock.recv(64)
        elapsed = int((time.monotonic() - start) * 1000)
        m = re.match(rb"HTTP/\d\.\d (\d{3})", head)
        return (int(m.group(1)), elapsed) if m else None
    except Exception:
        return None


def url_for(row):
    scheme = {"http": "http", "https": "https"}.get(row.get("kind", "tcp"), "http")
    if row["port"] in (443, 8443) and scheme == "http":
        scheme = "https"
    host = connect_host(row["addr"])
    if ":" in host:
        host = f"[{host}]"
    return f"{scheme}://{host}:{row['port']}/"
