"""Copy the PC app's presets and the AutoEQ index into the APK's assets.

    python tools/seed.py

seed.json      presets + order from %APPDATA%/EQ/state.json (unsaved drafts
               folded in, like the PC app's Export), used on first start only
autoeq.json    the AutoEQ index the PC app cached, so search works offline
"""
import json
import os
import shutil

SRC = os.path.join(os.environ["APPDATA"], "EQ")
OUT = os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "assets")

with open(os.path.join(SRC, "state.json"), encoding="utf-8") as f:
    s = json.load(f)
presets = dict(s["presets"])
presets.update({n: d for n, d in s.get("drafts", {}).items() if n in presets})
seed = {"order": [n for n in s["order"] if n in presets],
        "presets": {n: {"bands": p.get("bands", [])} for n, p in presets.items()}}
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "seed.json"), "w", encoding="utf-8") as f:
    json.dump(seed, f, indent=1, ensure_ascii=False)
shutil.copy(os.path.join(SRC, "autoeq", "index.json"), os.path.join(OUT, "autoeq.json"))
print("presets:", ", ".join(seed["order"]))
