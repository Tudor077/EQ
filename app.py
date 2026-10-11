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
TITLE = "EQ"


def one_instance():
    """Only one EQ at a time - two of them each hold the presets in memory and
    the last to save wins, which is how a whole set of presets got lost once.

    A second start brings the running window to the front and exits.
    `--replace` instead asks the running one to close (WM_CLOSE, so it saves
    on the way out), waits for it, and takes over - for restarting from a
    script without killing the user's window.
    """
    import ctypes
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.CreateMutexW.restype = ctypes.c_void_p
    h = k32.CreateMutexW(None, True, MUTEX)
    if k32.GetLastError() != 183:                      # ERROR_ALREADY_EXISTS
        return h
    hwnd = u32.FindWindowW(None, TITLE)
    if "--replace" not in sys.argv:
        if hwnd:
            u32.ShowWindow(hwnd, 9)                    # SW_RESTORE
            u32.SetForegroundWindow(hwnd)
        sys.exit(0)
    if hwnd:
        u32.PostMessageW(hwnd, 0x0010, 0, 0)           # WM_CLOSE
    if k32.WaitForSingleObject(ctypes.c_void_p(h), 10000) not in (0, 0x80):
        sys.exit("the running EQ did not close")
    return h


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
    api_box = {}

    def log(msg):
        if "api" in api_box:
            api_box["api"]._log.append(msg)

    eng = engine.Engine(log=log)
    spec = spectrum.Spectrum()
    spec.start()
    api = Api(eng, spec)
    api_box["api"] = api

    win = webview.create_window(TITLE, os.path.join(WEB, "index.html"), js_api=api,
                                width=1360, height=860, min_size=(1100, 720),
                                background_color="#000000")
    api._win = win
    win.events.closed += lambda: (spec.stop(), eng.close())
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
