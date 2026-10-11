"""Check that what Equalizer APO does is what the app draws.

    python verify_apo.py

Runs APO's own Benchmark.exe (same filter engine as the live driver) on white
noise at -20 dBFS through a test preset, then compares the measured transfer
function |FFT(out)| / |FFT(in)| with apo.response_db() - the curve the UI
draws. Leaves the user's real eq-app.txt as it found it.

Also checks that every line of the config parsed: Benchmark -v prints APO's
trace, and an unknown command shows up there as an error.
"""

import os
import subprocess
import sys
import tempfile
import wave

import numpy as np

import apo

RATE = 48000
TEST = {
    "enabled": True, "preamp": 0.0,
    "bands": [
        {"type": "bell", "freq": 1000, "gain": 6, "q": 1.0, "on": True},
        {"type": "lowcut", "freq": 100, "gain": 0, "q": 0.707, "on": True},
        {"type": "highshelf", "freq": 8000, "gain": -6, "q": 0.7, "on": True},
        {"type": "lowshelf", "freq": 250, "gain": 3, "q": 0.7, "on": True},
        {"type": "notch", "freq": 3000, "gain": 0, "q": 4, "on": True},
    ],
    "fx": {},
}


def wav_write(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").repeat(2).tobytes())


def wav_read(path):
    with wave.open(path) as w:
        raw = w.readframes(w.getnframes())
        ch, sw = w.getnchannels(), w.getsampwidth()
    a = np.frombuffer(raw, "<i2" if sw == 2 else "<f4").reshape(-1, ch)[:, 0]
    return a / 32768 if sw == 2 else a


def run(state, extra=()):
    cdir = apo.config_dir()
    ours = os.path.join(cdir, apo.OUR_FILE)
    saved = open(ours, encoding="utf-8").read() if os.path.exists(ours) else None
    tmp = tempfile.mkdtemp()
    src, dst = os.path.join(tmp, "in.wav"), os.path.join(tmp, "out.wav")
    rng = np.random.default_rng(1)
    x = rng.standard_normal(RATE * 6) * 0.1                 # -20 dBFS RMS
    wav_write(src, x)
    try:
        apo.ensure_include()
        apo.write(state)
        r = subprocess.run([os.path.join(apo.install_dir(), "Benchmark.exe"), "-i", src, "-o", dst,
                            "-v", "--nopause", *extra], capture_output=True, text=True, timeout=60)
    finally:
        if saved is None:
            os.remove(ours)
        else:
            with open(ours, "w", encoding="utf-8") as f:
                f.write(saved)
    return x, wav_read(dst), r.stdout + r.stderr


def transfer(x, y, nfft=8192):
    win = np.hanning(nfft)
    sx = sy = 0
    for i in range(0, len(x) - nfft, nfft // 2):
        X, Y = np.fft.rfft(x[i:i + nfft] * win), np.fft.rfft(y[i:i + nfft] * win)
        sx = sx + np.abs(X) ** 2
        sy = sy + np.abs(Y) ** 2
    f = np.fft.rfftfreq(nfft, 1 / RATE)
    return f, 10 * np.log10(sy / sx)


def main():
    x, y, log = run(TEST)
    errors = [l for l in log.splitlines() if "error" in l.lower() or "unknown" in l.lower()]
    f, h = transfer(x, y)
    worst = 0
    print(" freq    APO      app")
    for fq in (40, 70, 100, 150, 250, 500, 1000, 2000, 2800, 3000, 3200, 5000, 8000, 12000, 16000):
        i = np.argmin(abs(f - fq))
        m = np.median(h[max(i - 3, 0):i + 4])
        p = apo.response_db(TEST["bands"], fq)
        worst = max(worst, abs(m - p)) if fq != 3000 else worst   # notch bottom is -inf
        print(f"{fq:6d} {m:+7.2f}  {p:+7.2f}")
    print(f"worst difference: {worst:.2f} dB (below 60 Hz the 6 Hz FFT bins blur steep slopes)")
    print("config errors:", errors or "none")

    # crossfeed: the virtual channels must parse and change the output
    fx = dict(TEST, bands=[], fx={"crossfeed": 0.6, "loudness": True}, volume_db=-20)
    x2, y2, log2 = run(fx)
    err2 = [l for l in log2.splitlines() if "error" in l.lower() or "unknown" in l.lower()]
    print("crossfeed + loudness errors:", err2 or "none",
          "| output differs from input:", bool(np.abs(y2 - x2[:len(y2)]).max() > 1e-3))
    return 0 if worst < 0.75 and not errors and not err2 else 1


if __name__ == "__main__":
    sys.exit(main())
