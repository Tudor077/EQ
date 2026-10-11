"""Headphone correction from the AutoEQ project (github.com/jaakkopasanen/AutoEq).

AutoEQ has measured thousands of headphones and computed, for each, the
parametric EQ that brings it to a neutral target (Harman). We fetch two things,
only when asked:

    results/INDEX.md                     - the list: name -> folder
    <folder>/<name> ParametricEQ.txt     - Preamp + up to 10 filters

Both are cached in %APPDATA%\\EQ\\autoeq so a second look is offline.
"""

import json
import os
import re
import urllib.parse
import urllib.request

RAW = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results/"
CACHE = os.path.join(os.environ.get("APPDATA", "."), "EQ", "autoeq")
CODES = {"PK": "bell", "LSC": "lowshelf", "HSC": "highshelf", "LS": "lowshelf", "HS": "highshelf"}


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "eq-app"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def index():
    """[(name, source, folder)], from cache when there is one."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "index.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    md = _get(RAW + "INDEX.md")
    out = []
    # - [HyperX Cloud III](./oratory1990/over-ear/HyperX%20Cloud%20III) by oratory1990
    for m in re.finditer(r"^- \[(.+?)\]\(\./(.+?)\)(?: by (.+))?$", md, re.M):
        name, folder, src = m.group(1), urllib.parse.unquote(m.group(2)), (m.group(3) or "").strip()
        out.append([name, src, folder])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out


def search(query, limit=30):
    q = query.lower().split()
    hits = [e for e in index() if all(w in e[0].lower() for w in q)]
    return [{"name": n, "source": s, "folder": d} for n, s, d in hits[:limit]]


def parse(text):
    """AutoEQ ParametricEQ.txt -> {"preamp": dB, "bands": [...]}."""
    pre = re.search(r"Preamp:\s*(-?[\d.]+)\s*dB", text)
    bands = []
    for m in re.finditer(r"Filter\s*\d+:\s*ON\s+(\w+)\s+Fc\s+([\d.]+)\s*Hz\s+Gain\s+(-?[\d.]+)\s*dB\s+Q\s+([\d.]+)", text):
        t = CODES.get(m.group(1).upper())
        if t:
            bands.append({"type": t, "freq": float(m.group(2)), "gain": float(m.group(3)),
                          "q": float(m.group(4)), "on": True})
    return {"preamp": float(pre.group(1)) if pre else 0.0, "bands": bands}


def load(folder):
    name = folder.rstrip("/").split("/")[-1]
    safe = re.sub(r"[^\w.-]+", "_", folder)
    path = os.path.join(CACHE, safe + ".txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
    else:
        url = RAW + urllib.parse.quote(f"{folder}/{name} ParametricEQ.txt")
        text = _get(url)
        os.makedirs(CACHE, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    r = parse(text)
    r["name"] = name
    r["folder"] = folder
    return r
