"""Equalizer APO is the engine; this file speaks its config language.

APO reads C:\\Program Files\\EqualizerAPO\\config\\config.txt and re-reads it
the moment it changes, so a write here is heard within a few milliseconds and
costs no latency at all - the filtering happens inside Windows' audio engine.

We never own config.txt. It gets one line, `Include: eq-app.txt`, and
everything of ours lives in that file, so whatever the user (or APO's own
Editor) has in config.txt keeps working, and switching our app off is one
`Include` away from silence-free removal.

The config folder is writable without admin: the APO installer grants Users
modify rights on it, which is how its own Editor saves.
"""

import math
import os
import winreg

OUR_FILE = "eq-app.txt"
INCLUDE = f"Include: {OUR_FILE}"

# APO filter codes. Every one is the Q-taking variant (LSC/HSC for shelves,
# HPQ/LPQ for the cuts) so the slope is set the same way everywhere in the UI.
TYPES = {
    "bell": "PK",
    "lowshelf": "LSC",
    "highshelf": "HSC",
    "lowcut": "HPQ",
    "highcut": "LPQ",
    "notch": "NO",
}


def install_dir():
    """Where APO is installed, or None."""
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EqualizerAPO",
                                0, winreg.KEY_READ | view) as k:
                d = winreg.QueryValueEx(k, "InstallPath")[0]
                if os.path.isdir(d):
                    return d
        except OSError:
            pass
    d = r"C:\Program Files\EqualizerAPO"
    return d if os.path.isdir(d) else None


APO_CLSIDS = ("EACD2258-FCAC-4FF4-B36D-419E924A6D79", "EC1CC9CE-FAED-4822-828A-82A81A6F018F")
_RENDER = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
_NAME = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
_ADAPTER = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"


def apo_devices():
    """Names ("Headphones (HyperX Cloud III)") of active outputs APO sits on.

    Device Selector registers APO's two CLSIDs in each chosen endpoint's
    FxProperties; an output without them plays untouched, whatever we write.
    That was the first real-world failure: APO on the headphones, sound on
    the speakers, and an EQ that "does nothing".
    """
    out = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _RENDER, 0,
                              winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except OSError:
        return out
    i = 0
    while True:
        try:
            dev = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        try:
            with winreg.OpenKey(root, dev) as k:
                if winreg.QueryValueEx(k, "DeviceState")[0] != 1:
                    continue
            with winreg.OpenKey(root, dev + r"\Properties") as k:
                name = f"{winreg.QueryValueEx(k, _NAME)[0]} ({winreg.QueryValueEx(k, _ADAPTER)[0]})"
            found = False
            with winreg.OpenKey(root, dev + r"\FxProperties") as k:
                j = 0
                while not found:
                    try:
                        v = winreg.EnumValue(k, j)[1]
                    except OSError:
                        break
                    j += 1
                    found = any(c in str(v).upper() for c in APO_CLSIDS)
            if found:
                out.append(name)
        except OSError:
            continue
    return out


def open_device_selector():
    """APO's Device Selector, elevated and started IN its folder - from
    anywhere else it can't find its Qt plugins and dies with
    "no Qt platform plugin could be initialized"."""
    import ctypes
    d = install_dir()
    if d:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", os.path.join(d, "DeviceSelector.exe"),
                                            None, d, 1)


def config_dir():
    d = install_dir()
    return os.path.join(d, "config") if d else None


def _is_installer_default(text):
    """The config.txt APO ships with: -6 dB preamp and a bass-boost example.

    Left in place, that would sit in front of everything we do - the user
    would hear 6 dB less and a 20 Hz boost they never asked for.
    """
    t = text.lower()
    return "include: example.txt" in t and "preamp: -6 db" in t


def ensure_include():
    """Put our Include line into config.txt once. True when APO is usable."""
    cdir = config_dir()
    if not cdir:
        return False
    main = os.path.join(cdir, "config.txt")
    try:
        with open(main, encoding="utf-8-sig") as f:
            text = f.read()
    except OSError:
        text = ""
    if INCLUDE.lower() in text.lower():
        return True
    if _is_installer_default(text):
        backup = os.path.join(cdir, "config.before-eq-app.txt")
        if not os.path.exists(backup):
            with open(backup, "w", encoding="utf-8") as f:
                f.write(text)
        with open(main, "w", encoding="utf-8") as f:
            f.write(INCLUDE + "\n")
        return True
    with open(main, "a", encoding="utf-8") as f:
        if text and not text.endswith("\n"):
            f.write("\n")
        f.write(INCLUDE + "\n")
    return True


def _fmt(x):
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def band_line(i, b):
    t = TYPES[b["type"]]
    f = _fmt(b["freq"])
    q = _fmt(b.get("q", 0.707))
    if t in ("HPQ", "LPQ", "NO"):
        return f"Filter {i}: ON {t} Fc {f} Hz Q {q}"
    return f"Filter {i}: ON {t} Fc {f} Hz Gain {_fmt(b['gain'])} dB Q {q}"


def loudness_bands(volume_db):
    """Equal-loudness compensation as two shelves, sized by the volume.

    Turn music down and the ear loses bass first, then treble (ISO 226).
    So: the further below 0 dB the Windows volume is, the more bass and a
    little treble go back in. At full volume, nothing.

    Not APO's own LoudnessCorrection: that one takes over the volume
    attenuation itself, and with Windows' volume already down it attenuates
    a second time - in practice it made the sound all but disappear.

    No preamp is needed for these boosts: they are always smaller than the
    attenuation the volume applies after APO, so the output can't pass 0 dBFS.
    """
    down = max(0.0, -volume_db)
    bass = min(down * 0.3, 9.0)
    treble = min(down * 0.1, 3.0)
    out = []
    if bass >= 0.1:
        out.append({"type": "lowshelf", "freq": 100, "gain": round(bass, 1), "q": 0.7, "on": True})
    if treble >= 0.1:
        out.append({"type": "highshelf", "freq": 9000, "gain": round(treble, 1), "q": 0.7, "on": True})
    return out


def loudness_lines(volume_db):
    bands = loudness_bands(volume_db)
    lines = [f"# loudness at {_fmt(volume_db)} dB volume"]
    for b in bands:
        lines.append(band_line(0, b).replace("Filter 0:", "Filter:"))
    return lines


def crossfeed_lines(amount):
    """Headphone crossfeed, BS2B-style, out of APO's own building blocks.

    Each ear also gets a little of the other channel - low-passed (the head
    shadows the highs) and ~0.3 ms late (the extra path round the head). That
    is what speakers do naturally and headphones don't, and it is why hard-
    panned old stereo mixes stop sounding like they are inside your skull.

    `amount` 0..1 maps to 0..-6 dB of crossfeed relative to the direct signal.
    The two extra channels are APO virtual channels, mixed back and dropped.
    """
    if amount <= 0:
        return []
    g = 10 ** ((-15 + 9 * amount) / 20)       # -15 dB (subtle) .. -6 dB (strong)
    direct = 1 / (1 + g)                       # keep the sum from getting louder
    return [
        "# crossfeed",
        "Channel: all",
        "Copy: XL=R XR=L",
        "Channel: XL XR",
        "Filter: ON LPQ Fc 700 Hz Q 0.5",
        "Delay: 0.3 ms",
        "Channel: all",
        f"Copy: L={_fmt(direct)}*L+{_fmt(direct * g)}*XL R={_fmt(direct)}*R+{_fmt(direct * g)}*XR",
        "Channel: all",
    ]


def render(state):
    """The whole of eq-app.txt for one state dict (see engine.State)."""
    lines = ["# written by the EQ app - edits here are overwritten", ""]
    if not state.get("enabled", True):
        lines.append("# bypassed")
        return "\n".join(lines) + "\n"

    lines.append(f"Preamp: {_fmt(state.get('preamp', 0.0))} dB")

    n = 1
    layers = []
    if state.get("autoeq_on") and state.get("autoeq"):
        layers.append(("headphone correction: " + state["autoeq"].get("name", ""),
                       state["autoeq"]["bands"]))
    layers.append(("your EQ", [b for b in state.get("bands", []) if b.get("on", True)]))
    for title, bands in layers:
        lines.append(f"# {title}")
        for b in bands:
            lines.append(band_line(n, b))
            n += 1

    fx = state.get("fx", {})
    if fx.get("loudness"):
        lines += loudness_lines(float(state.get("volume_db", 0.0)))
    lines += crossfeed_lines(float(fx.get("crossfeed", 0)))
    return "\n".join(lines) + "\n"


def write(state):
    cdir = config_dir()
    if not cdir:
        return False
    path = os.path.join(cdir, OUR_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render(state))
    os.replace(tmp, path)          # APO never sees half a file
    return True


# --- the maths the UI also draws ------------------------------------------

RATE = 48000


def biquad(b):
    """RBJ coefficients (b0 b1 b2 a1 a2, a0 = 1) - same formulas APO uses."""
    f, q = b["freq"], max(b.get("q", 0.707), 0.05)
    a = 10 ** (b.get("gain", 0) / 40)
    w = 2 * math.pi * f / RATE
    cw, sw = math.cos(w), math.sin(w)
    al = sw / (2 * q)
    t = b["type"]
    if t == "bell":
        c = [1 + al * a, -2 * cw, 1 - al * a, 1 + al / a, -2 * cw, 1 - al / a]
    elif t in ("lowshelf", "highshelf"):
        s = 1 if t == "lowshelf" else -1
        sq = 2 * math.sqrt(a) * al
        c = [a * ((a + 1) - s * (a - 1) * cw + sq), 2 * s * a * ((a - 1) - s * (a + 1) * cw),
             a * ((a + 1) - s * (a - 1) * cw - sq), (a + 1) + s * (a - 1) * cw + sq,
             -2 * s * ((a - 1) + s * (a + 1) * cw), (a + 1) + s * (a - 1) * cw - sq]
    elif t == "lowcut":
        c = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2, 1 + al, -2 * cw, 1 - al]
    elif t == "highcut":
        c = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2, 1 + al, -2 * cw, 1 - al]
    elif t == "notch":
        c = [1, -2 * cw, 1, 1 + al, -2 * cw, 1 - al]
    else:
        raise ValueError(t)
    a0 = c[3]
    return [c[0] / a0, c[1] / a0, c[2] / a0, c[4] / a0, c[5] / a0]


def response_db(bands, freq):
    """Summed magnitude of `bands` at `freq`, in dB."""
    w = 2 * math.pi * freq / RATE
    z1 = complex(math.cos(-w), math.sin(-w))
    z2 = z1 * z1
    total = 0.0
    for b in bands:
        if not b.get("on", True):
            continue
        b0, b1, b2, a1, a2 = biquad(b)
        h = (b0 + b1 * z1 + b2 * z2) / (1 + a1 * z1 + a2 * z2)
        total += 20 * math.log10(max(abs(h), 1e-9))
    return total


def auto_preamp(bands):
    """Negative preamp that keeps the loudest point of the curve at 0 dB.

    Boosting a band without this clips the moment the music is already loud -
    the commonest reason a 'better' EQ sounds worse. Checked on a log grid of
    240 points; fine enough that a narrow peak can't slip between them.
    """
    peak = 0.0
    for i in range(240):
        f = 20 * (1000 ** (i / 239))
        peak = max(peak, response_db(bands, f))
    return -round(peak, 1)
