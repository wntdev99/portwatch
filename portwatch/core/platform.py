"""OS마다 다른 부분을 여기서 흡수한다.

Linux 에서는 외부 의존성 없이 ss 와 /proc 만으로 동작하고,
macOS 와 Windows 에서는 psutil 을 쓴다. psutil 이 없으면 macOS 는 lsof 로 물러난다.
"""
import os
import re
import subprocess
import sys

IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"

try:
    import psutil
except ImportError:
    psutil = None


class Unsupported(Exception):
    """이 환경에서는 포트 목록을 읽을 방법이 없다."""


def normalise_user(name):
    """'DOMAIN\\user' 나 대소문자 차이를 없애 비교할 수 있게 만든다."""
    if not name:
        return ""
    return name.replace("/", "\\").split("\\")[-1].casefold()


def current_user():
    if IS_WINDOWS:
        return normalise_user(os.environ.get("USERNAME", "")) or "?"
    import pwd
    return pwd.getpwuid(os.getuid()).pw_name


def run(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def run_full(cmd, timeout=5):
    """진단용. (종료 코드, stdout, stderr)"""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:
        return -1, "", str(exc)


def split_addr(endpoint):
    """'0.0.0.0:8080', '[::]:22', '127.0.0.1:5432' -> (주소, 포트)"""
    if endpoint.startswith("["):
        host, _, port = endpoint.rpartition("]:")
        return host[1:], port
    host, _, port = endpoint.rpartition(":")
    return host.split("%")[0], port


# ------------------------------------------------------------------ 소켓 목록

def _listeners_linux():
    rows = {}
    for line in run(["ss", "-ltnpH"]).splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        addr, port = split_addr(parts[3])
        if not port.isdigit():
            continue
        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        name, pid = (m.group(1), int(m.group(2))) if m else ("", 0)
        key = (addr, int(port))
        if key in rows and not name:
            continue
        rows[key] = {"addr": addr, "port": int(port), "name": name, "pid": pid}
    return list(rows.values())


def _listeners_psutil():
    rows = {}
    for conn in psutil.net_connections(kind="inet"):
        if conn.status != psutil.CONN_LISTEN or not conn.laddr:
            continue
        addr, port = conn.laddr.ip, conn.laddr.port
        name = ""
        if conn.pid:
            try:
                name = psutil.Process(conn.pid).name()
            except Exception:
                name = ""
        key = (addr, port)
        if key in rows and not conn.pid:
            continue
        rows[key] = {"addr": addr, "port": port, "name": name, "pid": conn.pid or 0}
    return list(rows.values())


def _listeners_lsof_plain():
    """lsof 평문 출력 파싱. 'python3 1234 me 5u IPv4 ... TCP 127.0.0.1:7897 (LISTEN)'"""
    rows = {}
    for line in run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"]).splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        name, pid = parts[0], parts[1]
        endpoint = next((p for p in reversed(parts) if ":" in p), "")
        addr, _, port = endpoint.rpartition(":")
        addr = addr.strip("[]")
        if addr in ("*", ""):
            addr = "0.0.0.0"
        if port.isdigit():
            rows[(addr, int(port))] = {
                "addr": addr, "port": int(port), "name": name,
                "pid": int(pid) if pid.isdigit() else 0}
    return list(rows.values())


def _listeners_lsof():
    """macOS 에서 psutil 없이 쓰는 길. 자기 소유 프로세스만 보인다."""
    rows = {}
    out = run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-F", "pcn"])
    pid = name = ""
    for line in out.splitlines():
        tag, value = line[:1], line[1:]
        if tag == "p":
            pid, name = value, ""
        elif tag == "c":
            name = value
        elif tag == "n":
            addr, _, port = value.rpartition(":")
            addr = addr.strip("[]")
            if addr in ("*", ""):
                addr = "0.0.0.0"
            if port.isdigit():
                rows[(addr, int(port))] = {
                    "addr": addr, "port": int(port), "name": name,
                    "pid": int(pid) if pid.isdigit() else 0}
    return list(rows.values()) or _listeners_lsof_plain()


def _listeners_netstat():
    """마지막 수단. 포트는 확실히 얻지만 프로세스는 알 수 없다.

    macOS 에서 psutil 이 권한으로 막히고 lsof 까지 조용히 빈 결과를 줄 때,
    적어도 '무엇이 열려 있는지' 는 보여 줄 수 있어야 한다.
    """
    rows = {}
    out = run(["netstat", "-an", "-p", "tcp"])
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[-1] != "LISTEN" or not parts[0].startswith("tcp"):
            continue
        local = parts[3]
        addr, _, port = local.rpartition(".")      # macOS 는 127.0.0.1.7896 형식
        if not port.isdigit():
            addr, _, port = local.rpartition(":")
        addr = addr.strip("[]")
        if addr in ("*", ""):
            addr = "0.0.0.0"
        if port.isdigit():
            rows[(addr, int(port))] = {"addr": addr, "port": int(port),
                                       "name": "", "pid": 0}
    return list(rows.values())


def listeners():
    """LISTEN 중인 TCP 소켓 목록. [{addr, port, name, pid}, ...]"""
    if IS_LINUX:
        rows = _listeners_linux()
        if rows or not psutil:
            return rows
        return _listeners_psutil()
    if psutil:
        try:
            rows = _listeners_psutil()
        except psutil.AccessDenied:
            rows = []       # macOS 는 root 가 아니면 거부한다
        # macOS 에서는 거부가 예외 대신 빈 목록으로 오기도 하므로 결과까지 본다.
        if rows or not IS_MAC:
            return rows
    if IS_MAC:
        return _listeners_lsof() or _listeners_netstat()
    raise Unsupported(
        "이 환경에서 포트를 읽으려면 psutil 이 필요합니다: pip install psutil")


# ------------------------------------------------------------------ 프로세스 정보

def _proc_linux(pid):
    info = {"user": "?", "cmdline": "", "cwd": "", "docker": False, "uptime": ""}
    try:
        info["user"] = run(["stat", "-c", "%U", f"/proc/{pid}"]).strip() or "?"
    except Exception:
        pass
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            info["cmdline"] = fh.read().replace(b"\0", b" ").decode(errors="replace").strip()
    except Exception:
        pass
    try:
        info["cwd"] = os.readlink(f"/proc/{pid}/cwd")
    except Exception:
        pass
    try:
        with open(f"/proc/{pid}/cgroup", encoding="utf-8") as fh:
            text = fh.read()
            info["docker"] = "docker" in text or "containerd" in text
    except Exception:
        pass
    info["uptime"] = run(["ps", "-o", "etime=", "-p", str(pid)]).strip()
    return info


def _proc_psutil(pid):
    info = {"user": "?", "cmdline": "", "cwd": "", "docker": False, "uptime": ""}
    try:
        proc = psutil.Process(pid)
    except Exception:
        return info
    try:
        info["user"] = normalise_user(proc.username()) if IS_WINDOWS else proc.username()
    except Exception:
        pass
    try:
        info["cwd"] = proc.cwd()
    except Exception:
        pass
    try:
        info["cmdline"] = " ".join(proc.cmdline())
    except Exception:
        pass
    try:
        import time as _time
        seconds = int(_time.time() - proc.create_time())
        info["uptime"] = f"{seconds // 86400}-{seconds % 86400 // 3600:02d}:" \
                         f"{seconds % 3600 // 60:02d}:{seconds % 60:02d}" \
            if seconds >= 86400 else \
            f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    except Exception:
        pass
    return info


def process_info(pid):
    """{user, cmdline, cwd, docker, uptime}"""
    if IS_LINUX:
        return _proc_linux(pid)
    if psutil:
        return _proc_psutil(pid)
    return {"user": "?", "cmdline": "", "cwd": "", "docker": False, "uptime": ""}


_docker_names = {}
_docker_stamp = 0.0


def docker_names():
    """컨테이너 ID 앞 12자리 -> 이름. 10초간 캐시한다."""
    global _docker_stamp
    import time
    now = time.time()
    if _docker_names and now - _docker_stamp < 10:
        return _docker_names
    out = run(["docker", "ps", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}"], timeout=3)
    if out:
        _docker_names.clear()
        for line in out.splitlines():
            cid, _, name = line.partition("\t")
            if cid and name:
                _docker_names[cid[:12]] = name
    _docker_stamp = now
    return _docker_names


def container_of(pid):
    if not IS_LINUX:
        return None
    try:
        with open(f"/proc/{pid}/cgroup", encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return None
    m = re.search(r"([0-9a-f]{12})[0-9a-f]*", text)
    return docker_names().get(m.group(1)) if m else None


# ------------------------------------------------------------------ 프로세스 제어

def terminate(pid):
    """정중한 종료 요청. 성공하면 True."""
    if IS_WINDOWS:
        if not psutil:
            raise Unsupported("psutil 이 필요합니다")
        psutil.Process(pid).terminate()        # TerminateProcess
        return True
    import signal
    os.kill(pid, signal.SIGTERM)
    return True


def force_kill(pid):
    if IS_WINDOWS:
        psutil.Process(pid).kill()
        return True
    import signal
    os.kill(pid, signal.SIGKILL)
    return True


def is_alive(pid):
    if IS_WINDOWS:
        return bool(psutil) and psutil.pid_exists(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
