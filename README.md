<div align="center">

# PortWatch

**See every port your machine is listening on — and open the web ones in a single click.**

A small, native GNOME app that answers the question every developer asks ten times a day:
*"What is running on port 8080 again, and who started it?"*

[한국어 README](README.ko.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-informational.svg)](#requirements)
[![GTK4 + libadwaita](https://img.shields.io/badge/GTK4-libadwaita-4a86cf.svg)](https://gnome.pages.gitlab.gnome.org/libadwaita/)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776ab.svg)](https://www.python.org/)
[![No dependencies to install](https://img.shields.io/badge/pip%20install-not%20required-success.svg)](#requirements)

<img src="docs/demo.gif" alt="Starring a port, searching by name, opening a server in the browser and scrolling through Docker containers" width="820">

<sub>Star a port · search by name or command line · click to open in the browser · Docker containers resolved by name</sub>

</div>

---

## Why

`ss -ltnp` tells you a port is open. It does not tell you that port `5173` is the Vite dev
server for the admin console you started three hours ago, that `6379` is a Redis container
that is reachable from every machine on your network, or that `8000` is the FastAPI app you
meant to kill before lunch.

PortWatch turns that raw socket list into something you can actually read — and act on.

## Features

- **Everything that listens, grouped the way you think about it** — Favourites, your own
  processes, Docker containers, and system/management ports in separate sections.
- **Click to open.** Any row that speaks HTTP opens in your default browser. No typing
  `localhost:` ever again.
- **Real names, not PIDs.** Reads `package.json`, the working directory and the command line
  to show `admin-console · Vite` instead of `node`.
- **Docker aware.** Resolves the container name behind a port, so you see `pg-main`, not `postgres`.
- **Exposure warnings.** Anything bound to `0.0.0.0` or `::` is flagged **외부 공개**
  (*publicly exposed*), because a dev server on your laptop should usually not be on the LAN.
- **Protocol detection.** Each port is probed once and labelled HTTP, HTTPS or plain TCP,
  so you never open a browser tab against a PostgreSQL socket.
- **Favourites.** Star the three ports you open all day; they float to the top.
- **Stop what you started.** A row you own offers *프로세스 종료* (terminate): a confirmation
  dialog showing the PID, command line and uptime, then `SIGTERM`. If the process is still
  alive three seconds later, PortWatch offers `SIGKILL` rather than sending it silently.
  Rows you do not own and rows inside a container never get the action — containers offer
  *copy `docker stop <name>`* instead.
- **Free a port.** *포트 비우기* (free a port) in the menu: type the port you want, and
  PortWatch finds whoever is holding it and offers to stop it. The answer to
  `Address already in use`, without a round trip through `lsof`.
- **Tells you what changed.** Ports that open or close between refreshes raise a toast, and a
  desktop notification when the window is not focused. Your dev server died quietly? You know.
- **Health at a glance.** Turn on *HTTP 상태 점검* and every HTTP row shows its status code and
  round-trip time — `200 · 12ms`, or an amber `500 · 340ms` for the one that is up but broken.
- **Exposure audit.** *외부 노출 점검* lists every port bound to `0.0.0.0`, and calls out the
  ones that are dangerous unauthenticated — Redis, PostgreSQL, MongoDB, a bare Docker API.
- **Restart what died.** A favourite remembers its command line and working directory, so a
  port that is no longer listening appears under *꺼진 즐겨찾기* with a play button.
- **SSH tunnels, readable.** A port opened by `ssh -L` is shown as
  `SSH 터널 · 8080 → 10.0.0.5:80 (gateway 경유)` instead of a bare `ssh`.
- **Live.** Auto-refreshes every 5 seconds, and only redraws when something actually changed.
- **Native look.** GTK4 + libadwaita, follows your system light/dark preference, keyboard driven.

<div align="center">
<img src="docs/screenshot-dark.png" alt="PortWatch in dark mode" width="700">
&nbsp;
<img src="docs/screenshot-light.png" alt="PortWatch in light mode" width="700">
<br>
<sub>Follows your system light/dark preference.</sub>
</div>

## Install

```bash
git clone https://github.com/wntdev99/portwatch.git
cd portwatch
make install
```

That is it — no virtualenv, no `pip install`. `make install` copies a single Python file to
`~/.local/bin/portwatch` and registers a desktop entry, so PortWatch shows up in your
application launcher.

<details>
<summary>Manual install (no <code>make</code>)</summary>

```bash
install -Dm755 portwatch ~/.local/bin/portwatch
install -Dm644 data/portwatch.desktop ~/.local/share/applications/portwatch.desktop
update-desktop-database ~/.local/share/applications
```

</details>

<details>
<summary>Uninstall</summary>

```bash
make uninstall          # removes the binary, the desktop entry and the config file
```

</details>

## Usage

Launch it from your application grid, or run `portwatch` in a terminal.

| Action | Shortcut |
| --- | --- |
| Refresh now | <kbd>Ctrl</kbd> + <kbd>R</kbd> |
| Search ports, names, command lines | <kbd>Ctrl</kbd> + <kbd>F</kbd> |
| Close search | <kbd>Esc</kbd> |
| Open the selected server in a browser | <kbd>Enter</kbd> |
| Close the window | <kbd>Ctrl</kbd> + <kbd>W</kbd> |

Each row also carries a star (favourite), an **open in browser** button, and a menu with
*copy URL*, *copy command line*, *open working directory* and *open in terminal*. For a
process you own, the menu ends with **프로세스 종료** (terminate), separated from the harmless
entries and guarded by a confirmation dialog.

The main menu holds the tools — *포트 비우기* (free a port) and *외부 노출 점검* (exposure
audit) — and the view switches: system ports, auto refresh, HTTP health checks and change
notifications.

## Requirements

| | |
| --- | --- |
| OS | Linux with a GTK4 desktop (developed and tested on Ubuntu 24.04 / GNOME 46) |
| Python | 3.10 or newer |
| Libraries | `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1` |
| Tools | `ss` (from `iproute2`); `docker` is optional and only used for container names |

On Ubuntu and Debian these are present on a default GNOME install. If not:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 iproute2
```

## How it works

1. `ss -ltnpH` lists every TCP socket in `LISTEN` state.
2. For each socket with a readable owner, `/proc/<pid>/{cmdline,cwd,cgroup}` fills in the
   command line, the working directory and whether the process lives inside a container.
3. Each port is probed **once** with a single `GET / HTTP/1.0` to classify it as HTTP, HTTPS
   or plain TCP. The result is cached, so the 5-second refresh costs nothing.
4. IPv4 and IPv6 rows for the same process are merged into one entry.

Everything runs as your user. PortWatch never asks for root and never writes to the system.

## Configuration

Settings live in `~/.config/portwatch.json` and are written by the app itself:

```json
{
  "pinned": [3000, 8000],
  "show_system": false,
  "auto_refresh": true,
  "check_health": false,
  "notify_changes": true,
  "commands": {
    "3000": {
      "title": "storefront · Next.js",
      "cmdline": "node node_modules/.bin/next dev --port 3000",
      "cwd": "/home/you/work/storefront"
    }
  }
}
```

`commands` is written when you star a port, and is what the restart button replays.
`check_health` is off by default: it sends one `GET /` per HTTP port on every refresh, which
shows up in your dev server's log.

Two environment variables are available, mainly for development and for taking screenshots:

| Variable | Effect |
| --- | --- |
| `PORTWATCH_DEMO=1` | Renders a fixed set of fake services instead of reading real sockets |
| `PORTWATCH_COLOR_SCHEME=prefer-light\|prefer-dark` | Overrides the system light/dark preference |

## Known limitations

- **Ports owned by other users show as "프로세스 정보 없음".** The kernel does not reveal
  another user's process to `ss` unless you are root. PortWatch deliberately does not run
  itself as root; for those rows it falls back to a well-known-port guess (`6379 → Redis`).
- **TCP only.** UDP listeners are not shown. Most things you want to click are TCP.
- **Terminating is limited to your own processes.** PortWatch sends signals as your user and
  never escalates. A container's process is left to `docker stop`, because killing PID 1
  inside a container only triggers its restart policy.
- **The interface is in Korean.** The app was written for a Korean-speaking team.
  Internationalisation is welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing

Issues and pull requests are welcome. PortWatch is deliberately one file; please keep
changes small and dependency-free. See [CONTRIBUTING.md](CONTRIBUTING.md) for the details.

## License

[MIT](LICENSE)
