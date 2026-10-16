"""Pack EQ into one EQ.exe.

    python build.py

The result lands in dist\\EQ.exe. Build files stay in the temp folder.

web/ goes in WITHOUT the Nothing fonts: they belong to Nothing and can't be
redistributed. The app looks for them in %APPDATA%\\EQ\\fonts at start-up
and otherwise uses Windows' own fonts.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "EQ"
OUR_FONTS = (".woff2", ".woff", ".otf", ".ttf")


def make_icon(path):
    """The same drawing the tray uses - see icon.py."""
    import icon
    return icon.save_ico(path)


def main():
    tmp = os.path.join(tempfile.gettempdir(), "eq_build")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    web = os.path.join(tmp, "web")
    shutil.copytree(os.path.join(HERE, "web"), web,
                    ignore=lambda d, names: [n for n in names if n.lower().endswith(OUR_FONTS)])
    icon = make_icon(os.path.join(tmp, "eq.ico"))
    shutil.copy(icon, os.path.join(web, "favicon.ico"))

    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", NAME, "--icon", icon,
        "--workpath", os.path.join(tmp, "work"), "--specpath", tmp,
        "--distpath", os.path.join(HERE, "dist"),
        "--add-data", f"{web}{os.pathsep}web",
        "--hidden-import", "pyaudiowpatch", "--hidden-import", "pycaw.pycaw",
        "--hidden-import", "win32gui", "--hidden-import", "win32process", "--hidden-import", "psutil",
        "--hidden-import", "clr_loader", "--hidden-import", "tray", "--hidden-import", "autostart", "--hidden-import", "icon",
        "--hidden-import", "win32api", "--hidden-import", "win32con", "--hidden-import", "win32com.client", "--hidden-import", "webview.platforms.winforms",
        # numpy is all we need; on this machine scipy/torch would drag in gigabytes
        *[a for m in ("torch", "torchgen", "onnx", "sympy", "scipy", "pandas", "matplotlib", "networkx", "tkinter")
          for a in ("--exclude-module", m)],
        os.path.join(HERE, "app.py"),
    ]
    print(" ".join(cmd))
    subprocess.check_call(cmd)
    out = os.path.join(HERE, "dist", NAME + ".exe")
    print(f"\ndone: {out}  ({os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
