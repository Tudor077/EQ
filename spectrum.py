"""Live spectrum of what is actually coming out of the speakers.

WASAPI loopback on the default output device (pyaudiowpatch), so it shows the
sound AFTER Equalizer APO - move a band and you see the music move with it.

Analysis: Hann-windowed 8192-point FFT at 48 kHz (~6 Hz bins, enough to
resolve 20 Hz), folded into 1/12-octave bands, then a fast-attack /
slow-release ballistic like a hardware analyser, so peaks jump and fall back
gently instead of flickering.
"""

import threading
import time

import numpy as np

N_FFT = 8192
BANDS_PER_OCT = 12
F_LO, F_HI = 20.0, 20000.0


class Spectrum:
    def __init__(self):
        n = int(np.log2(F_HI / F_LO) * BANDS_PER_OCT) + 1
        self.freqs = F_LO * 2 ** (np.arange(n) / BANDS_PER_OCT)
        self.db = np.full(n, -100.0)
        self.device = ""
        self.error = ""
        self._buf = np.zeros(N_FFT, np.float32)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._edges = None
        self._rate = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="spectrum", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def snapshot(self):
        """[(freq, dB)] rounded, for the UI."""
        with self._lock:
            return [round(float(d), 1) for d in self.db]

    def _setup_bins(self, rate):
        f = np.fft.rfftfreq(N_FFT, 1 / rate)
        lo = self.freqs * 2 ** (-0.5 / BANDS_PER_OCT)
        hi = self.freqs * 2 ** (0.5 / BANDS_PER_OCT)
        self._edges = [(np.searchsorted(f, a), max(np.searchsorted(f, b), np.searchsorted(f, a) + 1))
                       for a, b in zip(lo, hi)]
        self._win = np.hanning(N_FFT).astype(np.float32)
        self._norm = 2.0 / self._win.sum()
        self._rate = rate

    @staticmethod
    def _windows_default():
        """The default output's name, asked of Windows itself, every time.

        PortAudio reads the device list once, when PyAudio() is created, so
        asking the same PyAudio "what is the default now?" keeps answering
        with the device from startup - the analyser stayed on the old output
        after a switch to the Bluetooth headphones. Windows (via pycaw) knows.
        """
        from pycaw.pycaw import AudioUtilities
        return AudioUtilities.GetSpeakers().FriendlyName

    def _run(self):
        import comtypes
        import pyaudiowpatch as pa
        comtypes.CoInitialize()
        while not self._stop.is_set():
            p = pa.PyAudio()
            try:
                dev = p.get_default_wasapi_loopback()
                rate = int(dev["defaultSampleRate"])
                ch = int(dev["maxInputChannels"])
                self.device = dev["name"].replace(" [Loopback]", "")
                self._setup_bins(rate)
                stream = p.open(format=pa.paFloat32, channels=ch, rate=rate, input=True,
                                input_device_index=dev["index"], frames_per_buffer=1024)
                self.error = ""
                last_dev_check = time.monotonic()
                try:
                    opened_as = self._windows_default()   # compare Windows with Windows
                except Exception:
                    opened_as = None
                while not self._stop.is_set():
                    avail = stream.get_read_available()
                    if avail <= 0:
                        time.sleep(0.008)
                    else:
                        raw = stream.read(avail, exception_on_overflow=False)
                        x = np.frombuffer(raw, np.float32).reshape(-1, ch).mean(axis=1)
                        self._push(x)
                    self._analyse()
                    if time.monotonic() - last_dev_check > 2:
                        last_dev_check = time.monotonic()
                        try:
                            now = self._windows_default()
                        except Exception:
                            now = opened_as
                        if now != opened_as:
                            break                       # output changed: new PyAudio, new list
                stream.close()
            except Exception as e:                      # no device, device vanished...
                self.error = str(e)
                time.sleep(1)
            finally:
                p.terminate()

    def _push(self, x):
        n = len(x)
        if n >= N_FFT:
            self._buf[:] = x[-N_FFT:]
        else:
            self._buf[:-n] = self._buf[n:]
            self._buf[-n:] = x

    def _analyse(self):
        now = time.monotonic()
        if now - getattr(self, "_t", 0) < 1 / 40:          # 40 analyses a second
            return
        dt = now - getattr(self, "_t", now)
        self._t = now
        mag = np.abs(np.fft.rfft(self._buf * self._win)) * self._norm
        pw = mag ** 2
        cur = np.array([10 * np.log10(pw[a:b].sum() + 1e-14) for a, b in self._edges])
        fall = 30 * dt                                      # 30 dB per second release
        with self._lock:
            self.db = np.where(cur > self.db, cur, np.maximum(cur, self.db - fall))
