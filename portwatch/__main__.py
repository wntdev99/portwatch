"""실행 진입점. 어떤 화면을 쓸지 고른다."""
import argparse
import sys

from . import __version__
from .core import platform as plat


def gtk_available():
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        return True
    except Exception:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="portwatch",
        description="열려 있는 포트를 한눈에 보고, 웹 서버는 클릭 한 번으로 엽니다.")
    parser.add_argument("--web", action="store_true",
                        help="브라우저 화면으로 실행합니다 (모든 OS)")
    parser.add_argument("--gtk", action="store_true",
                        help="GTK4 네이티브 창으로 실행합니다 (Linux)")
    parser.add_argument("--port", type=int, default=7878,
                        help="웹 화면이 쓸 로컬 포트 (기본 7878)")
    parser.add_argument("--no-browser", action="store_true",
                        help="웹 화면을 띄우되 브라우저를 자동으로 열지 않습니다")
    parser.add_argument("--version", action="version", version=f"PortWatch {__version__}")
    args = parser.parse_args(argv)

    use_gtk = args.gtk or (not args.web and plat.IS_LINUX and gtk_available())
    if use_gtk:
        if not gtk_available():
            print("GTK4 와 libadwaita 를 찾지 못했습니다. --web 으로 실행해 보세요.",
                  file=sys.stderr)
            return 1
        from .gtk_app import main as gtk_main
        return gtk_main()

    if not plat.IS_LINUX and not plat.psutil:
        print("이 환경에서는 psutil 이 필요합니다:  pip install psutil", file=sys.stderr)
        return 1
    from .web.server import serve
    serve(port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
