"""Win32 implementation of :class:`slayerbot.backend.Backend` (ctypes only, no dependencies).

Importing this module is safe on any OS; instantiating ``Win32Backend`` is not.
"""
from __future__ import annotations

import sys
import time
from typing import List, Optional, Tuple

from .imaging import Frame

IS_WINDOWS = sys.platform == "win32"

_WM_LBUTTONDOWN = 0x0201
_WM_LBUTTONUP = 0x0202
_MK_LBUTTON = 0x0001
_PW_RENDERFULLCONTENT = 0x00000002
_SW_MINIMIZE = 6
_SW_RESTORE = 9
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_DWMWA_CLOAKED = 14

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    class Win32Backend:
        """Window lookup, PrintWindow capture and input through user32/gdi32."""

        def __init__(self) -> None:
            # Private DLL instances so our argtypes/restypes never leak into other code.
            self._u = ctypes.WinDLL("user32", use_last_error=True)
            self._g = ctypes.WinDLL("gdi32", use_last_error=True)
            self._d = ctypes.WinDLL("dwmapi", use_last_error=True)
            self._declare_signatures()

        def _declare_signatures(self) -> None:
            u, g, d = self._u, self._g, self._d
            hwnd, hdc = wintypes.HWND, wintypes.HDC
            # Handle-returning functions need explicit types: without them ctypes
            # truncates 64-bit handles to 32-bit ints and captures silently break.
            u.GetDC.restype, u.GetDC.argtypes = hdc, [hwnd]
            u.ReleaseDC.argtypes = [hwnd, hdc]
            u.PrintWindow.argtypes = [hwnd, hdc, wintypes.UINT]
            u.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
            u.IsWindowVisible.argtypes = [hwnd]
            u.IsWindow.argtypes = [hwnd]
            u.IsIconic.argtypes = [hwnd]
            u.GetWindowTextLengthW.argtypes = [hwnd]
            u.GetWindowTextW.argtypes = [hwnd, wintypes.LPWSTR, ctypes.c_int]
            u.GetClientRect.argtypes = [hwnd, ctypes.POINTER(wintypes.RECT)]
            u.GetWindowRect.argtypes = [hwnd, ctypes.POINTER(wintypes.RECT)]
            u.ClientToScreen.argtypes = [hwnd, ctypes.POINTER(wintypes.POINT)]
            u.PostMessageW.argtypes = [hwnd, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            u.SetForegroundWindow.argtypes = [hwnd]
            u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
            u.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
            u.ShowWindow.argtypes = [hwnd, ctypes.c_int]
            u.SetWindowPos.argtypes = [hwnd, hwnd, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            g.CreateCompatibleDC.restype, g.CreateCompatibleDC.argtypes = hdc, [hdc]
            g.CreateCompatibleBitmap.restype = wintypes.HBITMAP
            g.CreateCompatibleBitmap.argtypes = [hdc, ctypes.c_int, ctypes.c_int]
            g.SelectObject.restype, g.SelectObject.argtypes = ctypes.c_void_p, [hdc, ctypes.c_void_p]
            g.DeleteObject.argtypes = [ctypes.c_void_p]
            g.DeleteDC.argtypes = [hdc]
            g.GetDIBits.argtypes = [
                hdc, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
            ]
            d.DwmGetWindowAttribute.argtypes = [hwnd, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

        # -- lookup ------------------------------------------------------------

        def _is_cloaked(self, hwnd: int) -> bool:
            """DWM-hidden windows (suspended UWP apps) stay "visible" but render nothing."""
            value = wintypes.DWORD()
            hr = self._d.DwmGetWindowAttribute(hwnd, _DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
            return hr == 0 and value.value != 0

        def _enumerate(self) -> List[Tuple[int, str]]:
            found: List[Tuple[int, str]] = []

            def callback(hwnd, _lparam):
                if self._u.IsWindowVisible(hwnd):
                    length = self._u.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        self._u.GetWindowTextW(hwnd, buf, length + 1)
                        if not self._is_cloaked(hwnd):
                            found.append((hwnd, buf.value))
                return True

            self._u.EnumWindows(_WNDENUMPROC(callback), 0)
            return found

        def list_windows(self) -> List[str]:
            return [title for _, title in self._enumerate()]

        def find_window(self, title: str) -> Optional[int]:
            needle = title.strip().lower()
            if not needle:
                return None
            windows = self._enumerate()
            for hwnd, text in windows:
                if text.lower() == needle:
                    return hwnd
            for hwnd, text in windows:
                if needle in text.lower():
                    return hwnd
            return None

        def is_window(self, hwnd: int) -> bool:
            return bool(self._u.IsWindow(hwnd))

        def client_size(self, hwnd: int) -> Tuple[int, int]:
            rect = wintypes.RECT()
            self._u.GetClientRect(hwnd, ctypes.byref(rect))
            return (rect.right - rect.left, rect.bottom - rect.top)

        # -- capture -----------------------------------------------------------

        def capture(self, hwnd: int) -> Optional[Frame]:
            width, height = self.client_size(hwnd)
            if width <= 0 or height <= 0:
                return None
            hdc = self._u.GetDC(hwnd)
            if not hdc:
                return None
            mem_dc = self._g.CreateCompatibleDC(hdc)
            bitmap = self._g.CreateCompatibleBitmap(hdc, width, height)
            previous = self._g.SelectObject(mem_dc, bitmap)
            try:
                ok = self._u.PrintWindow(hwnd, mem_dc, _PW_RENDERFULLCONTENT) or self._u.PrintWindow(hwnd, mem_dc, 0)
                if not ok:
                    return None
                info = _BITMAPINFOHEADER()
                info.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
                info.biWidth, info.biHeight = width, height  # positive height = bottom-up rows
                info.biPlanes, info.biBitCount, info.biCompression = 1, 24, 0
                row_size = ((width * 3 + 3) // 4) * 4
                buf = ctypes.create_string_buffer(row_size * height)
                if not self._g.GetDIBits(mem_dc, bitmap, 0, height, buf, ctypes.byref(info), 0):
                    return None
                return Frame(width, height, buf.raw)
            finally:
                self._g.SelectObject(mem_dc, previous)
                self._g.DeleteObject(bitmap)
                self._g.DeleteDC(mem_dc)
                self._u.ReleaseDC(hwnd, hdc)

        # -- input -------------------------------------------------------------

        def click(self, hwnd: int, x: int, y: int, foreground: bool) -> None:
            if foreground:
                self._click_foreground(hwnd, x, y)
            else:
                self._click_message(hwnd, x, y)

        def _click_message(self, hwnd: int, x: int, y: int) -> None:
            """Post the click straight to the window queue: no focus, no real mouse movement."""
            lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
            self._u.PostMessageW(hwnd, _WM_LBUTTONDOWN, _MK_LBUTTON, lparam)
            time.sleep(0.05)
            self._u.PostMessageW(hwnd, _WM_LBUTTONUP, 0, lparam)

        def _click_foreground(self, hwnd: int, x: int, y: int) -> None:
            """Real click: raises the window and moves the actual cursor.

            Needed because the Play Games emulator reads raw input and ignores posted messages.
            """
            if self.is_minimized(hwnd):
                self.restore(hwnd)
                time.sleep(0.5)
            origin = wintypes.POINT(0, 0)
            self._u.ClientToScreen(hwnd, ctypes.byref(origin))
            self._u.SetForegroundWindow(hwnd)
            time.sleep(0.3)
            self._u.SetCursorPos(origin.x + x, origin.y + y)
            self._u.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            self._u.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

        # -- window state ------------------------------------------------------

        def minimize(self, hwnd: int) -> None:
            self._u.ShowWindow(hwnd, _SW_MINIMIZE)

        def restore(self, hwnd: int) -> None:
            self._u.ShowWindow(hwnd, _SW_RESTORE)

        def is_minimized(self, hwnd: int) -> bool:
            return bool(self._u.IsIconic(hwnd))

        def move_resize(self, hwnd: int, x: Optional[int], y: Optional[int], width: int, height: int) -> None:
            if x is None or y is None:
                rect = wintypes.RECT()
                self._u.GetWindowRect(hwnd, ctypes.byref(rect))
                x = rect.left if x is None else x
                y = rect.top if y is None else y
            self._u.SetWindowPos(hwnd, None, x, y, width, height, _SWP_NOZORDER | _SWP_NOACTIVATE)

else:

    class Win32Backend:  # type: ignore[no-redef]
        """Placeholder so imports work off Windows; it cannot be instantiated."""

        def __init__(self) -> None:
            raise OSError("slayer-bot controls Google Play Games for PC and only runs on Windows")
