"""EQ - the window.

    python app.py

A pywebview window (Edge WebView2, already part of Windows 11) around web/,
because a curve you drag with the mouse at 60 FPS is a canvas job, and Tk's
canvas isn't one. Everything the page can do goes through Api below.

The sound itself never passes through this program: Equalizer APO does the
filtering inside Windows' audio engine. So the EQ keeps working with this
window closed - only per-app switching and the hotkeys need it running.
"""

import os
import sys
import threading

import webview

import autoeq
import engine
import spectrum

HERE = os.path.dirname(os.path.abspath(__file__))
# frozen by PyInstaller, web/ is unpacked to a temp folder, not next to the exe
WEB = os.path.join(getattr(sys, "_MEIPASS", HERE), "web")


class Api:
    def __init__(self, eng, spec):
        self._e = eng
        self._s = spec
        self._log = []

    # reads
    def state(self):
        st = self._e.snapshot()
        st["device"] = self._s.device
        st["log"] = self._log[-20:]
        return st

    def spectrum(self):
        return self._s.snapshot()

    def spectrum_freqs(self):
        return [round(float(f), 2) for f in self._s.freqs]

    # edits
    def set_bands(self, bands):
        self._e.set_bands(bands)

    def set_fx(self, fx):
        self._e.set_fx(fx)

    def set(self, key, value):
        self._e.set(key, value)

    def activate(self, name):
        self._e.activate(name)

    def save(self):
        self._e.save()

    def revert(self):
        self._e.revert()

    def save_as(self, name):
        self._e.save_as(name)

    def rename(self, old, new):
        self._e.rename(old, new)

    def delete(self, name):
        self._e.delete(name)

    def set_rule(self, exe, preset):
        self._e.set_rule(exe, preset)

    # headphones
    def autoeq_search(self, q):
        try:
            return {"ok": True, "results": autoeq.search(q)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def autoeq_load(self, folder):
        try:
            p = autoeq.load(folder)
            self._e.set_autoeq(p)
            return {"ok": True, "profile": p}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def autoeq_clear(self):
        self._e.set_autoeq(None)

    # start with Windows
    def autostart_get(self):
        import autostart
        return autostart.is_enabled()

    def autostart_set(self, on):
        import autostart
        return autostart.set(bool(on))

    def open_apo_selector(self):
        """APO's own device picker - which outputs the EQ applies to."""
        engine.apo.open_device_selector()

    # export / import: a file the user picks, outside %APPDATA%
    def export_presets(self):
        r = self._win.create_file_dialog(webview.SAVE_DIALOG, save_filename="eq-presets.json",
                                         file_types=("EQ presets (*.json)",))
        if not r:
            return {"ok": False, "cancelled": True}
        path = r if isinstance(r, str) else r[0]
        try:
            n = self._e.export_to(path)
            return {"ok": True, "path": path, "count": n}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    def import_presets(self):
        r = self._win.create_file_dialog(webview.OPEN_DIALOG, file_types=("EQ presets (*.json)",))
        if not r:
            return {"ok": False, "cancelled": True}
        try:
            names = self._e.import_from(r[0])
            return {"ok": True, "names": names}
        except (OSError, ValueError, KeyError) as e:
            return {"ok": False, "error": str(e)}


MUTEX = r"Local\EQApp.single-instance"
EV_SHOW = r"Local\EQApp.show"            # "bring the window up" from a second start
EV_QUIT = r"Local\EQApp.quit"            # "save and exit" from --replace
TITLE = "EQ"


def _event(name):
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.CreateEventW.restype = ctypes.c_void_p
    return k32.CreateEventW(None, False, False, name)       # auto-reset


def one_instance():
    """Only one EQ at a time - two of them each hold the presets in memory and
    the last to save wins, which is how a whole set of presets got lost once.

    A second start asks the running one to show its window and exits (the
    window may be hidden in the tray, so a plain "bring to front" isn't
    enough). `--replace` asks the running one to quit - it saves on the way
    out - waits for it, and takes over: for restarting from a script without
    killing the user's EQ.
    """
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    h = k32.CreateMutexW(None, True, MUTEX)
    if k32.GetLastError() != 183:                      # ERROR_ALREADY_EXISTS
        return h
    if "--replace" not in sys.argv:
        k32.SetEvent(ctypes.c_void_p(_event(EV_SHOW)))
        sys.exit(0)
    k32.SetEvent(ctypes.c_void_p(_event(EV_QUIT)))
    if k32.WaitForSingleObject(ctypes.c_void_p(h), 10000) not in (0, 0x80):
        sys.exit("the running EQ did not close")
    return h


def _watch(name, fn):
    """Call fn whenever another process signals the named event."""
    import ctypes
    k32 = ctypes.windll.kernel32
    ev = ctypes.c_void_p(_event(name))

    def loop():
        while True:
            if k32.WaitForSingleObject(ev, 0xFFFFFFFF) == 0:
                try:
                    fn()
                except Exception:
                    pass
    threading.Thread(target=loop, daemon=True).start()


FONTS = ("NType82-Headline.woff2", "NType82-Regular.woff2", "NType82Mono-Regular.woff2", "NDot-55.otf")


def bring_fonts():
    """The Nothing typefaces aren't ours to ship, so the release has none and
    falls back to Windows' own fonts. Whoever has them can drop them into
    %APPDATA%/EQ/fonts; they are copied next to the page at start-up
    (into the unpacked bundle when frozen), where the CSS looks for them."""
    import shutil
    src = os.path.join(os.environ.get("APPDATA", ""), "EQ", "fonts")
    dst = os.path.join(WEB, "fonts")
    if not os.path.isdir(src):
        return
    os.makedirs(dst, exist_ok=True)
    for f in FONTS:
        s, d = os.path.join(src, f), os.path.join(dst, f)
        if os.path.exists(s) and not os.path.exists(d):
            try:
                shutil.copy2(s, d)
            except OSError:
                pass


def main():
    _mutex = one_instance()                            # held until we exit
    bring_fonts()
    hidden = "--hidden" in sys.argv                    # started at logon: straight to the tray
    api_box = {}

    def log(msg):
        if "api" in api_box:
            api_box["api"]._log.append(msg)

    eng = engine.Engine(log=log)
    spec = spectrum.Spectrum()
    spec.active = not hidden                           # no FFT while nobody looks at it
    spec.start()
    api = Api(eng, spec)
    api_box["api"] = api

    win = webview.create_window(TITLE, os.path.join(WEB, "index.html"), js_api=api,
                                width=1360, height=860, min_size=(1100, 720),
                                background_color="#000000", hidden=hidden)
    api._win = win
    quitting = {"now": False}

    def show():
        spec.active = True
        win.show()
        win.restore()

    def quit_all():
        quitting["now"] = True
        win.destroy()

    def on_closing():
        # the X hides to the tray when there is one; Quit in the tray really quits
        if quitting["now"] or tray is None:
            return True
        spec.active = False
        win.hide()
        return False

    tray = None
    try:
        import autostart
        import tray as tray_mod

        def state():
            st = eng.snapshot()
            tip = "EQ - " + ("bypassed" if not st["enabled"] else st["active"])
            return {"enabled": st["enabled"], "autostart": autostart.is_enabled(), "tip": tip}

        def bypass():
            eng.set("enabled", not eng.s["enabled"])

        tray = tray_mod.Tray({"open": show, "bypass": bypass, "autostart": autostart.set, "quit": quit_all}, state)
        tray.start()
        eng.listeners.append(tray.refresh)             # the tip follows preset switches
    except Exception as e:
        log(f"tray icon unavailable: {e}")

    _watch(EV_SHOW, show)
    _watch(EV_QUIT, quit_all)
    win.events.closing += on_closing
    win.events.closed += lambda: (spec.stop(), eng.close(), tray and tray.stop())
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
