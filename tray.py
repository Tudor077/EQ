"""The notification-area icon, straight on Shell_NotifyIcon (pywin32 is
already a dependency, so no pystray).

Its own thread and message loop; it only calls the callbacks it is given.
If it can't start, EQ carries on as an ordinary window - a missing icon must
never stop the EQ itself.
"""

import os
import tempfile
import threading

import win32api
import win32con
import win32gui

import icon

WM_TRAY = win32con.WM_USER + 20
M_OPEN, M_BYPASS, M_AUTOSTART, M_QUIT = 1001, 1002, 1003, 1004


class Tray(threading.Thread):
    """on = {"open": fn, "bypass": fn, "autostart": fn(on), "quit": fn}
    state = fn() -> {"enabled": bool, "autostart": bool, "tip": str}"""

    def __init__(self, on, state):
        super().__init__(daemon=True, name="tray")
        self.on, self.state = on, state
        self.hwnd = None
        self.ico = os.path.join(tempfile.gettempdir(), "eq_tray.ico")
        icon.save_ico(self.ico, sizes=(16, 32))

    def stop(self):
        if self.hwnd:
            try:
                win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
            except win32gui.error:
                pass

    def refresh(self):
        """Update the hover text (the active preset, bypass)."""
        if self.hwnd:
            try:
                self._notify(win32gui.NIM_MODIFY)
            except win32gui.error:
                pass

    def _notify(self, msg):
        h = win32gui.LoadImage(0, self.ico, win32con.IMAGE_ICON, 0, 0, win32con.LR_LOADFROMFILE)
        tip = (self.state().get("tip") or "EQ")[:127]
        win32gui.Shell_NotifyIcon(msg, (self.hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                                        WM_TRAY, h, tip))

    def _on_tray(self, hwnd, msg, wparam, lparam):
        if lparam in (win32con.WM_LBUTTONUP, win32con.WM_LBUTTONDBLCLK):
            self.on["open"]()
        elif lparam == win32con.WM_RBUTTONUP:
            st = self.state()
            m = win32gui.CreatePopupMenu()
            win32gui.AppendMenu(m, win32con.MF_STRING, M_OPEN, "Open EQ")
            win32gui.AppendMenu(m, win32con.MF_STRING | (0 if st.get("enabled") else win32con.MF_CHECKED),
                                M_BYPASS, "Bypass")
            win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(m, win32con.MF_STRING | (win32con.MF_CHECKED if st.get("autostart") else 0),
                                M_AUTOSTART, "Start with Windows")
            win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(m, win32con.MF_STRING, M_QUIT, "Quit")
            x, y = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(self.hwnd)
            win32gui.TrackPopupMenu(m, win32con.TPM_LEFTALIGN, x, y, 0, self.hwnd, None)
            win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
        return 0

    def _on_command(self, hwnd, msg, wparam, lparam):
        cmd = win32api.LOWORD(wparam)
        if cmd == M_OPEN:
            self.on["open"]()
        elif cmd == M_BYPASS:
            self.on["bypass"]()
        elif cmd == M_AUTOSTART:
            self.on["autostart"](not self.state().get("autostart"))
        elif cmd == M_QUIT:
            self.on["quit"]()
        self.refresh()
        return 0

    def _on_close(self, hwnd, msg, wparam, lparam):
        win32gui.DestroyWindow(hwnd)
        return 0

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 0))
        except win32gui.error:
            pass
        win32gui.PostQuitMessage(0)
        return 0

    def run(self):
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "EQTray"
        wc.lpfnWndProc = {WM_TRAY: self._on_tray, win32con.WM_COMMAND: self._on_command,
                          win32con.WM_CLOSE: self._on_close, win32con.WM_DESTROY: self._on_destroy}
        try:
            win32gui.RegisterClass(wc)
        except win32gui.error:
            pass
        self.hwnd = win32gui.CreateWindow("EQTray", "EQ tray", win32con.WS_OVERLAPPED, 0, 0, 0, 0, 0, 0,
                                          wc.hInstance, None)
        self._notify(win32gui.NIM_ADD)
        win32gui.PumpMessages()
