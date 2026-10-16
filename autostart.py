"""Starting EQ at logon, through a shortcut in the Startup folder.

A shortcut rather than a registry Run key: you can see it, move it or delete
it from Explorer, and Task Manager's Startup tab lists it by name.

The shortcut starts EQ with --hidden: straight to the tray, no window, so the
per-app switching, hotkeys and loudness are working from the moment you log on.

    python autostart.py on | off | status
"""

import os
import sys

NAME = "EQ.lnk"
HERE = os.path.dirname(os.path.abspath(__file__))


def link_path():
    return os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup", NAME)


def target_args():
    """What the shortcut launches: the exe when frozen; otherwise the built exe
    if there is one, else pythonw (no console window) with app.py."""
    if getattr(sys, "frozen", False):
        return sys.executable, "--hidden", os.path.dirname(sys.executable)
    exe = os.path.join(HERE, "dist", "EQ.exe")
    if os.path.exists(exe):
        return exe, "--hidden", os.path.dirname(exe)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return (pyw if os.path.exists(pyw) else sys.executable), '"%s" --hidden' % os.path.join(HERE, "app.py"), HERE


def is_enabled():
    return os.path.exists(link_path())


def enable():
    try:
        import win32com.client
        target, args, workdir = target_args()
        lnk = win32com.client.Dispatch("WScript.Shell").CreateShortCut(link_path())
        lnk.TargetPath = target
        lnk.Arguments = args
        lnk.WorkingDirectory = workdir
        lnk.Description = "EQ - parametric equalizer for Windows"
        lnk.Save()
        return True
    except Exception:
        return False


def disable():
    try:
        if os.path.exists(link_path()):
            os.remove(link_path())
        return True
    except OSError:
        return False


def set(on):
    return enable() if on else disable()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "on":
        print("on" if enable() else "failed")
    elif cmd == "off":
        print("off" if disable() else "failed")
    else:
        t, a, _ = target_args()
        print("start at logon:", "yes" if is_enabled() else "no")
        print("would run:", t, a)
