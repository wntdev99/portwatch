"""행을 가지고 실제로 무언가 하는 동작들. OS 차이는 platform 이 흡수한다."""
import os
import shlex
import subprocess
import webbrowser

from . import platform as plat

LINUX_TERMINALS = [
    ("gnome-terminal", "--working-directory={cwd}"),
    ("kgx", "--working-directory={cwd}"),
    ("ptyxis", "--working-directory={cwd}"),
    ("konsole", "--workdir={cwd}"),
    ("xfce4-terminal", "--working-directory={cwd}"),
    ("alacritty", "--working-directory={cwd}"),
    ("kitty", "--directory={cwd}"),
    ("x-terminal-emulator", None),
]


def open_url(url):
    webbrowser.open(url)


def open_dir(path):
    if not os.path.isdir(path):
        return False
    if plat.IS_WINDOWS:
        os.startfile(path)                                  # noqa: S606
    elif plat.IS_MAC:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def open_terminal(path):
    """작업 디렉터리에서 터미널을 연다. 성공하면 True."""
    if not os.path.isdir(path):
        return False
    if plat.IS_WINDOWS:
        for cmd in (["wt.exe", "-d", path], ["cmd.exe", "/c", "start", "cmd.exe"]):
            try:
                subprocess.Popen(cmd, cwd=path)
                return True
            except Exception:
                continue
        return False
    if plat.IS_MAC:
        subprocess.Popen(["open", "-a", "Terminal", path])
        return True

    import shutil
    for name, flag in LINUX_TERMINALS:
        exe = shutil.which(name)
        if not exe:
            continue
        cmd = [exe] + ([flag.format(cwd=path)] if flag else [])
        try:
            subprocess.Popen(cmd, cwd=path, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue
    return False


def restart(saved):
    """기억해 둔 명령으로 다시 띄운다. (성공 여부, 메시지)"""
    if not os.path.isdir(saved["cwd"]):
        return False, "작업 디렉터리가 더 이상 없습니다"
    try:
        args = saved["cmdline"] if plat.IS_WINDOWS else shlex.split(saved["cmdline"])
        kwargs = {} if plat.IS_WINDOWS else {"start_new_session": True}
        subprocess.Popen(args, cwd=saved["cwd"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **kwargs)
    except Exception as exc:
        return False, f"실행하지 못했습니다 — {exc}"
    return True, f"{saved['title']} 을(를) 실행했습니다"


def terminate(pid):
    """(성공 여부, 메시지)"""
    try:
        plat.terminate(pid)
    except ProcessLookupError:
        return False, "이미 종료된 프로세스입니다"
    except PermissionError:
        return False, "권한이 없어 종료하지 못했습니다"
    except Exception as exc:
        return False, f"종료하지 못했습니다 — {exc}"
    return True, "종료 신호를 보냈습니다"


def force_kill(pid):
    try:
        plat.force_kill(pid)
    except Exception as exc:
        return False, f"강제 종료하지 못했습니다 — {exc}"
    return True, "강제 종료 신호를 보냈습니다"


def is_alive(pid):
    return plat.is_alive(pid)


def docker_stop_command(container):
    return f"docker stop {container}"
