# EQ for Android

Phone counterpart of the Windows app in this repo. Parametric EQ that runs **only while
headphones are connected** (Bluetooth, BLE, USB DAC/headset, wired) and turns
itself off when they disconnect.

- Same curve maths as the PC app (RBJ biquads); `FiltersTest` checks it against
  vectors from `apo.py`. Android has no app-reachable parametric EQ, so the
  curve is sampled into 64 DynamicsProcessing bands.
- Global mode = DynamicsProcessing on session 0 (all apps). If a phone blocks
  that, Per-app mode attaches to sessions that players announce.
- Each pair of headphones remembers its own preset, on/off and AutoEQ profile.
- First start is seeded with the PC presets: `python tools/seed.py` copies them
  (and the AutoEQ index) into `app/src/main/assets` before a build.
- Import/Export use the PC app's Export JSON format.

Build: `gradlew assembleRelease` -> `app/build/outputs/apk/release/app-release.apk`
(signed with the debug key).
