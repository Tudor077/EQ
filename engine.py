"""State, presets, per-app switching and hotkeys. No UI in here.

The model:
    presets     name -> {bands, fx}            the curves you build
    active      which preset is applied now
    base        the preset to fall back to when no app rule matches
    rules       exe -> preset                  "BeamNG gets Cabin", ...
    drafts      name -> {bands, fx}            unsaved edits. Every change lands
                here, never in `presets`, until Save. So Save and Save as are
                different things: Save overwrites the preset, Save as makes a
                new one and leaves the original as it was saved. A draft
                survives switching away (an app coming to the front must not
                eat half an hour of tweaking) and a restart.
    autoeq      headphone correction, kept apart from presets: it belongs to
                the headphones, not to the song, so switching presets must not
                drop it

Every change is written to APO through a 40 ms trailing throttle: dragging a
band sends ~60 updates a second and APO only needs to hear the last one.
Saved to %APPDATA%\\EQ\\state.json half a second after the last change.
"""

import copy
import ctypes
import json
import os
import threading
import time
from ctypes import wintypes

import apo

DIR = os.path.join(os.environ.get("APPDATA", "."), "EQ")
PATH = os.path.join(DIR, "state.json")

FLAT = {"bands": [], "fx": {"loudness": False, "crossfeed": 0.0}}


def _b(t, f, g=0.0, q=0.707):
    return {"type": t, "freq": f, "gain": g, "q": q, "on": True}


STARTERS = {
    "Flat": FLAT,
    "Bass": {"bands": [_b("lowshelf", 90, 6, 0.7), _b("bell", 250, -1.5, 1.0)],
             "fx": {"loudness": False, "crossfeed": 0.0}},
    "Voice": {"bands": [_b("lowcut", 90, 0, 0.7), _b("bell", 300, -2, 1.0),
                        _b("bell", 3000, 3, 1.0), _b("highshelf", 9000, -1.5, 0.7)],
              "fx": {"loudness": False, "crossfeed": 0.0}},
    "Night": {"bands": [_b("lowshelf", 120, -3, 0.7), _b("highshelf", 6000, -2, 0.7)],
              "fx": {"loudness": True, "crossfeed": 0.4}},
    "Cabin": {"bands": [_b("lowcut", 22, 0, 0.7), _b("bell", 55, 4, 1.2), _b("lowshelf", 160, 3, 0.7),
                        _b("bell", 900, -2, 0.9), _b("highshelf", 2200, -9, 0.7), _b("highcut", 7000, 0, 0.7)],
              "fx": {"loudness": False, "crossfeed": 0.6}},
}

DEFAULT = {
    "enabled": True,
    "auto_preamp": True,
    "preamp": 0.0,
    "presets": copy.deepcopy(STARTERS),
    "order": list(STARTERS),
    "active": "Flat",
    "base": "Flat",
    "rules": {},
    "auto_switch": True,
    "autoeq": None,
    "autoeq_on": False,
    "drafts": {},
}


class Engine:
    def __init__(self, log=print):
        self.log = log
        self.lock = threading.RLock()
        self.s = self._load()
        self.apo_ok = apo.ensure_include()
        self.foreground = ""
        self.volume_db = 0.0
        self.listeners = []
        self._dirty_apo = threading.Event()
        self._save_at = None
        self._stop = threading.Event()
        threading.Thread(target=self._writer, daemon=True).start()
        threading.Thread(target=self._watch_foreground, daemon=True).start()
        threading.Thread(target=self._hotkeys, daemon=True).start()
        threading.Thread(target=self._watch_volume, daemon=True).start()
        self._dirty_apo.set()

    # ---- persistence ----

    def _load(self):
        s = copy.deepcopy(DEFAULT)
        try:
            with open(PATH, encoding="utf-8") as f:
                s.update(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
        s["drafts"] = {k: v for k, v in s.get("drafts", {}).items() if k in s["presets"]}
        for p in list(s["presets"].values()) + list(s["drafts"].values()):
            p["bands"] = sorted(p.get("bands", []), key=lambda b: b["freq"])    # numbered low to high
        if s["active"] not in s["presets"]:
            s["active"] = next(iter(s["presets"]), "Flat")
        s["order"] = [n for n in s["order"] if n in s["presets"]] + \
                     [n for n in s["presets"] if n not in s["order"]]
        return s

    def _backup(self):
        """Keep a copy of state.json at most every 10 minutes, the last 30.

        Presets are hours of listening; one bad write must never be the only
        copy. Kept in %APPDATA%/EQ/backups/state-YYYYmmdd-HHMMSS.json
        """
        if not os.path.exists(PATH):
            return
        bdir = os.path.join(DIR, "backups")
        os.makedirs(bdir, exist_ok=True)
        old = sorted(f for f in os.listdir(bdir) if f.startswith("state-"))
        if old and time.time() - os.path.getmtime(os.path.join(bdir, old[-1])) < 600:
            return
        import shutil
        shutil.copy2(PATH, os.path.join(bdir, time.strftime("state-%Y%m%d-%H%M%S.json")))
        for f in old[:-29]:
            os.remove(os.path.join(bdir, f))

    def _save(self):
        os.makedirs(DIR, exist_ok=True)
        try:
            self._backup()
        except OSError as e:
            self.log(f"backup failed: {e}")
        tmp = PATH + ".tmp"
        with self.lock:
            data = json.dumps(self.s, indent=1)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, PATH)

    def _changed(self, save=True):
        self._dirty_apo.set()
        if save:
            self._save_at = time.monotonic() + 0.5
        for fn in list(self.listeners):
            try:
                fn()
            except Exception:
                pass

    # ---- what APO gets ----

    def _cur(self):
        a = self.s["active"]
        return self.s["drafts"].get(a) or self.s["presets"][a]

    def _draft(self):
        """The active preset's draft, made from the saved version on first edit."""
        a = self.s["active"]
        if a not in self.s["drafts"]:
            self.s["drafts"][a] = copy.deepcopy(self.s["presets"][a])
        return self.s["drafts"][a]

    def current(self):
        """What is being applied - the draft if there is one - as a copy."""
        with self.lock:
            return copy.deepcopy(self._cur())

    def apo_state(self):
        with self.lock:
            p = self._cur()
            ae = self.s["autoeq"] if self.s["autoeq_on"] else None
            bands = [b for b in p["bands"] if b.get("on", True)]
            all_bands = (ae["bands"] if ae else []) + bands
            pre = apo.auto_preamp(all_bands) if self.s["auto_preamp"] else self.s["preamp"]
            return {"enabled": self.s["enabled"], "preamp": pre, "bands": p["bands"],
                    "autoeq": ae, "autoeq_on": bool(ae), "fx": p.get("fx", {}),
                    "volume_db": self.volume_db}

    def _writer(self):
        while not self._stop.is_set():
            if self._dirty_apo.wait(0.1):
                self._dirty_apo.clear()
                try:
                    if self.apo_ok or apo.ensure_include():
                        self.apo_ok = True
                        apo.write(self.apo_state())
                except OSError as e:
                    self.log(f"APO write failed: {e}")
                time.sleep(0.04)
            if self._save_at and time.monotonic() >= self._save_at:
                self._save_at = None
                try:
                    self._save()
                except OSError as e:
                    self.log(f"save failed: {e}")

    # ---- edits from the UI ----

    def snapshot(self):
        with self.lock:
            s = copy.deepcopy(self.s)
        st = self.apo_state()
        s["effective_preamp"] = st["preamp"]
        s["apo_ok"] = self.apo_ok
        s["apo_dir"] = apo.install_dir()
        now = time.monotonic()
        if now - getattr(self, "_devs_t", -99) > 5:          # registry walk: not every second
            self._devs_t, self._devs = now, apo.apo_devices()
        s["apo_devices"] = self._devs
        s["foreground"] = self.foreground
        s["current"] = self.current()
        s["dirty"] = self.s["active"] in s["drafts"]
        s["volume_db"] = self.volume_db
        return s

    def set_bands(self, bands):
        with self.lock:
            d = self._draft()
            d["bands"] = sorted(bands, key=lambda b: b["freq"])
            self._drop_if_clean()
        self._changed()

    def set_fx(self, fx):
        with self.lock:
            self._draft().setdefault("fx", {}).update(fx)
            self._drop_if_clean()
        self._changed()

    def _drop_if_clean(self):
        """Undoing an edit by hand makes the preset clean again."""
        a = self.s["active"]
        if self.s["drafts"].get(a) == self.s["presets"][a]:
            del self.s["drafts"][a]

    def save(self):
        """Write the draft into the active preset."""
        with self.lock:
            a = self.s["active"]
            if a in self.s["drafts"]:
                self.s["presets"][a] = self.s["drafts"].pop(a)
        self._changed()

    def revert(self):
        """Throw the draft away; back to the preset as saved."""
        with self.lock:
            self.s["drafts"].pop(self.s["active"], None)
        self._changed()

    def set(self, key, value):
        if key not in ("enabled", "auto_preamp", "preamp", "auto_switch", "autoeq_on", "base"):
            raise KeyError(key)
        with self.lock:
            self.s[key] = value
        self._changed()

    def activate(self, name, manual=True):
        with self.lock:
            if name not in self.s["presets"] or name == self.s["active"]:
                return
            self.s["active"] = name
            if manual:
                # picked by hand while no rule applies: that becomes the base
                if not self._rule_for(self.foreground):
                    self.s["base"] = name
        self._changed()

    def save_as(self, name):
        name = name.strip()[:32]
        if not name:
            return
        with self.lock:
            # the new preset gets what you hear; the one you started from
            # stays as it was saved
            self.s["presets"][name] = self.current()
            self.s["drafts"].pop(self.s["active"], None)
            self.s["drafts"].pop(name, None)
            if name not in self.s["order"]:
                self.s["order"].append(name)
            self.s["active"] = name
        self._changed()

    def rename(self, old, new):
        new = new.strip()[:32]
        with self.lock:
            if old not in self.s["presets"] or not new or new in self.s["presets"]:
                return
            self.s["presets"][new] = self.s["presets"].pop(old)
            if old in self.s["drafts"]:
                self.s["drafts"][new] = self.s["drafts"].pop(old)
            self.s["order"] = [new if n == old else n for n in self.s["order"]]
            for k in ("active", "base"):
                if self.s[k] == old:
                    self.s[k] = new
            self.s["rules"] = {e: (new if p == old else p) for e, p in self.s["rules"].items()}
        self._changed()

    def delete(self, name):
        with self.lock:
            if name not in self.s["presets"] or len(self.s["presets"]) <= 1:
                return
            del self.s["presets"][name]
            self.s["drafts"].pop(name, None)
            self.s["order"] = [n for n in self.s["order"] if n != name]
            first = self.s["order"][0]
            for k in ("active", "base"):
                if self.s[k] == name:
                    self.s[k] = first
            self.s["rules"] = {e: p for e, p in self.s["rules"].items() if p != name}
        self._changed()

    # ---- export / import ----

    def export_to(self, path):
        """Presets (with unsaved drafts folded in as they are now), order,
        app rules and the headphone profile, as one JSON file."""
        with self.lock:
            presets = copy.deepcopy(self.s["presets"])
            for n, d in self.s["drafts"].items():
                presets[n] = copy.deepcopy(d)
            data = {"app": "eq", "version": 1, "exported": time.strftime("%Y-%m-%d %H:%M"),
                    "order": list(self.s["order"]), "presets": presets,
                    "rules": dict(self.s["rules"]), "autoeq": self.s["autoeq"]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        return len(presets)

    def import_from(self, path):
        """Add the file's presets. Nothing existing is overwritten: a name
        that is taken gets " (2)", " (3)"... Rules come along for apps that
        have none yet. Returns the names added."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("presets"), dict):
            raise ValueError("the file has no EQ presets in it")
        added, renamed = [], {}
        with self.lock:
            order = data.get("order") or list(data["presets"])
            for name in order + [n for n in data["presets"] if n not in order]:
                p = data["presets"].get(name)
                if not isinstance(p, dict) or not isinstance(p.get("bands"), list):
                    continue
                new, i = name, 2
                while new in self.s["presets"]:
                    new, i = f"{name} ({i})", i + 1
                renamed[name] = new
                p = {"bands": sorted(p["bands"], key=lambda b: b["freq"]),
                     "fx": dict(p.get("fx") or {})}
                self.s["presets"][new] = p
                self.s["order"].append(new)
                added.append(new)
            for exe, pname in (data.get("rules") or {}).items():
                if exe not in self.s["rules"] and pname in renamed:
                    self.s["rules"][exe] = renamed[pname]
            if not self.s["autoeq"] and data.get("autoeq"):
                self.s["autoeq"] = data["autoeq"]
        self._changed()
        return added

    def set_rule(self, exe, preset):
        exe = exe.strip().lower()
        if not exe:
            return
        if not exe.endswith(".exe"):
            exe += ".exe"
        with self.lock:
            if preset:
                self.s["rules"][exe] = preset
            else:
                self.s["rules"].pop(exe, None)
        self._changed()

    def set_autoeq(self, profile):
        with self.lock:
            self.s["autoeq"] = profile
            self.s["autoeq_on"] = bool(profile)
        self._changed()

    # ---- per-app switching ----

    def _rule_for(self, exe):
        return self.s["rules"].get((exe or "").lower())

    def _watch_foreground(self):
        import psutil
        import win32gui
        import win32process
        last = None
        while not self._stop.is_set():
            time.sleep(0.5)
            try:
                hwnd = win32gui.GetForegroundWindow()
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                exe = psutil.Process(pid).name().lower()
            except Exception:
                continue
            if exe == last:
                continue
            last = exe
            if exe in ("python.exe", "pythonw.exe", "eq.exe"):
                continue                    # looking at us: don't switch away under the user
            self.foreground = exe
            if not self.s["auto_switch"]:
                continue
            want = self._rule_for(exe) or self.s["base"]
            if want in self.s["presets"] and want != self.s["active"]:
                self.activate(want, manual=False)
                self.log(f"{exe} -> {want}")

    # ---- the Windows volume, for loudness ----

    def _watch_volume(self):
        """Follow the master volume of the default output, in dB.

        Loudness needs it: how much bass to put back depends on how far the
        volume is turned down. Only rewrites APO when loudness is on and the
        volume moved by half a dB or more.
        """
        import comtypes
        from ctypes import POINTER, cast
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        comtypes.CoInitialize()

        def endpoint():
            # newer pycaw wraps the device and hands out .EndpointVolume;
            # older versions return the raw IMMDevice to Activate yourself
            dev = AudioUtilities.GetSpeakers()
            ep = getattr(dev, "EndpointVolume", None)
            if ep is None:
                iface = dev.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
                ep = cast(iface, POINTER(IAudioEndpointVolume))
            did = getattr(dev, "id", None) or dev.GetId()
            return did, ep

        vol, dev_id, top, last_check = None, None, 0.0, 0
        while not self._stop.is_set():
            time.sleep(0.25)
            try:
                if vol is None or time.monotonic() - last_check > 3:
                    last_check = time.monotonic()
                    did, ep = endpoint()
                    if did != dev_id or vol is None:
                        dev_id, vol = did, ep
                        # the slider's top isn't always 0 dB - the Realtek
                        # here goes to +12 - so "turned down" is measured
                        # from the device's own maximum
                        top = float(vol.GetVolumeRange()[1])
                db = float(vol.GetMasterVolumeLevel()) - top
            except Exception:
                vol = None
                continue
            if abs(db - self.volume_db) >= 0.5:
                self.volume_db = db
                if self._cur().get("fx", {}).get("loudness"):
                    self._dirty_apo.set()

    # ---- global hotkeys: Ctrl+Alt+1..9 presets, Ctrl+Alt+0 bypass ----

    def _hotkeys(self):
        user32 = ctypes.windll.user32
        MOD = 0x0001 | 0x0002 | 0x4000          # Alt | Ctrl | NoRepeat
        ok = []
        for i in range(10):
            if user32.RegisterHotKey(None, 100 + i, MOD, 0x30 + i):
                ok.append(i)
        if len(ok) < 10:
            self.log(f"hotkeys: {10 - len(ok)} of Ctrl+Alt+0..9 are taken by another app")
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:            # WM_HOTKEY
                i = msg.wParam - 100
                if i == 0:
                    self.set("enabled", not self.s["enabled"])
                else:
                    order = self.s["order"]
                    if i - 1 < len(order):
                        self.activate(order[i - 1])

    def close(self):
        self._stop.set()
        self._save()
