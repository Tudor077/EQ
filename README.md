# EQ

A parametric equalizer for the whole of Windows, with per-app presets, live
spectrum and headphone correction.

## Install

1. Install **Equalizer APO** (free, open source):
   [sourceforge.net/projects/equalizerapo](https://sourceforge.net/projects/equalizerapo/).
   In its Device Selector tick the outputs you listen on, then restart.
2. Download `EQ.exe` from [Releases](../../releases) and run it. No install,
   one file. Settings live in `%APPDATA%\EQ`.

If the output you're on has no APO, EQ says so and has a button that opens
Device Selector.

From source (Python 3.11+):

```
pip install -r requirements.txt
python app.py
python build.py      # -> dist\EQ.exe
```

## How it works

The sound never passes through this program. **Equalizer APO** does the
filtering inside Windows' own audio engine: zero added latency, works in every
game, and keeps working with this window closed. The app is the brain and the
face - it writes `eq-app.txt` into APO's config folder, and APO re-reads it
within milliseconds.

`config.txt` gets a single line, `Include: eq-app.txt`. The default config APO
installs (a -6 dB preamp and a bass-boost example) is replaced on first run and
kept as `config.before-eq-app.txt`.

APO only filters the outputs ticked in its **DeviceSelector** (Start menu →
Equalizer APO → Device Selector), and needs a restart after a change there.

## Using it

- **Graph**: double-click adds a band, drag moves frequency and gain (Shift =
  fine), mouse wheel sets the width (Q), right-click picks the type, Del or
  double-click on a band removes it. The red fill is the selected band's own
  shape; the white line is what you hear. The grey area behind is the live
  spectrum of what actually leaves the speakers - after the EQ.
- **Auto preamp**: lowers the volume by exactly the curve's highest boost, so a
  +6 dB band can't clip. On by default.
- **Headphones (AutoEQ)**: search your model; the correction from the AutoEQ
  project is a separate layer under your curve (dashed line), so it stays when
  you switch presets.
- **Save / Save as**: edits go into a draft (red dot on the preset); *Save*
  (Ctrl+S) writes it into the preset, *Save as* (Ctrl+Shift+S) makes a new
  preset and leaves the original as saved, *Renunță* throws the draft away.
  Drafts survive switching presets and restarts.
- **Band numbers** always run low to high: drag a band past its neighbour and
  it takes that number.
- **Effects** (per preset): Loudness (bass and a little treble put back as the
  Windows volume goes down - our own, because APO's LoudnessCorrection
  attenuated on top of Windows' volume and all but muted the sound) and Crossfeed (a little of each channel, low-passed and 0.3 ms
  late, into the other ear: headphones stop sounding "inside your head").
- **Per app**: with the app in front, *Add* ties it to the current preset; the
  preset switches by itself when that app comes to the front, and goes back to
  *Default* otherwise.
- **Hotkeys**: Ctrl+Alt+1..9 = presets in order, Ctrl+Alt+0 = bypass.
- **Tray and start with Windows**: closing the window hides it to the tray;
  per-app switching, hotkeys and loudness keep running. The tray menu has
  Open, Bypass, *Start with Windows* and Quit. Starting with Windows puts an
  `EQ.lnk` in your Startup folder that runs `EQ.exe --hidden` - straight to
  the tray (`python autostart.py on | off | status` does the same).

## Checked, not assumed

`python verify_apo.py` runs APO's own `Benchmark.exe` - the same engine as the
driver - on white noise through a test preset with every filter type, and
compares the measured response with the curve the UI draws. Last run: within
0.5 dB everywhere (the 0.5 is at 40 Hz, where 6 Hz FFT bins blur a steep
slope), no config errors, and the crossfeed's virtual channels parse and change
the output.

## Files

| | |
|---|---|
| `app.py` | the window (pywebview) and the API the page calls |
| `engine.py` | state, presets, per-app switching, hotkeys |
| `apo.py` | the APO config language, plus the filter maths the UI also uses |
| `tray.py`, `autostart.py`, `icon.py` | tray icon, the Startup shortcut, the icon drawing |
| `spectrum.py` | WASAPI loopback analyser (pyaudiowpatch) |
| `autoeq.py` | AutoEQ index and profiles, cached in `%APPDATA%\EQ\autoeq` |
| `web/` | the UI; opened as a plain page it runs on a mock, for working on it without touching the sound |

Settings and presets: `%APPDATA%\EQ\state.json`, with a copy at most every
10 minutes in `%APPDATA%\EQ\backups` (last 30 kept), and **Exportă / Importă**
in the preset panel for a file of your own. Import never overwrites: a taken
name gets " (2)".

One copy at a time: starting it again shows the running one's window, even
from the tray. `EQ.exe --replace` (or `python app.py --replace`) closes the running one properly (it saves on the way
out) and takes over - use that, not killing the process, to restart it.

Not done yet: a limiter and dynamic bass boost need real dynamics processing,
which APO only offers through VST plugins.

The look follows the Nothing brand reference, but the Nothing fonts aren't
shipped - see `web/fonts/README.md`.
