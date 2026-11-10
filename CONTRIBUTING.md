# Contributing to PortWatch

Thanks for taking the time. PortWatch is small on purpose, and the goal is to keep it that way.

## Ground rules

1. **One file, no dependencies.** The whole app is `portwatch`, a single Python script that
   runs on a stock GNOME install. Please do not add anything that requires `pip install`.
2. **Never require root.** Reading another user's process is out of scope. If information is
   not available to the current user, the UI says so instead of escalating.
3. **Keep the refresh cheap.** The 5-second refresh must not probe a port twice or shell out
   per row. Cache anything that cannot change.

## Development

```bash
git clone https://github.com/wntdev99/portwatch.git
cd portwatch
make run        # run against your real sockets
make demo       # run against fixed fake data — useful for UI work and screenshots
make check      # byte-compile
```

`PORTWATCH_COLOR_SCHEME=prefer-light make demo` forces the light theme, which is how the
screenshots in `docs/` are produced. The demo GIF is recorded the same way: run `make demo`,
size the window to 980x700, capture with `ffmpeg -f x11grab`, and convert with a
`palettegen`/`paletteuse` pair. In demo mode a row click only shows the toast — it does not
launch a browser, because the demo ports do not exist.

## Pull requests

- Describe what you saw before and after. A screenshot of the affected rows helps a lot.
- Test with at least one Docker container running, and once with `show_system` enabled,
  since those paths exercise the code that is easiest to break.
- Match the existing style: 4 spaces, descriptive names, comments only where the reason is
  not obvious from the code.

## Verifying without taking over the screen

GUI changes are checked on a virtual display so the work never steals focus from whoever is
using the machine:

```bash
Xvfb :99 -screen 0 1200x900x24 &
env -u DBUS_SESSION_BUS_ADDRESS DISPLAY=:99 PORTWATCH_DEMO=1 \
    dbus-run-session -- ./portwatch &
DISPLAY=:99 xwininfo -root -tree | grep PortWatch     # find the window id
DISPLAY=:99 xwd -id <id> -out shot.xwd                # capture it
```

`dbus-run-session` matters: PortWatch is a single-instance `Adw.Application`, so without its
own session bus a second copy just wakes the one already running on the real display.

Logic that does not need pixels — signals, dialogs, change detection — is checked by importing
the file and driving the `Window` object without ever calling `present()`.

## Good first issues

- **Internationalisation.** Strings are currently Korean literals in the source. Moving them
  to `gettext` and adding an English catalogue would make the app usable far more widely.
- **UDP listeners** as an optional section.
