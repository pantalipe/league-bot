"""Win32 implementation of :class:`league_bot.backend.Backend` (ctypes only, no dependencies).

Importing this module is safe on any OS; instantiating ``Win32Backend`` is not.
"""
from __future__ import annotations

import sys
import time
from typing import List, Optional, Tuple

from .backend import InputSample
from .imaging import Frame

IS_WINDOWS = sys.platform == "win32"

_WM_LBUTTONDOWN = 0x0201
_WM_LBUTTONUP = 0x0202
_MK_LBUTTON = 0x0001
_PW_RENDERFULLCONTENT = 0x00000002
_SW_SHOWMINNOACTIVE = 7
_SW_MINIMIZE = 6
_SW_SHOWNOACTIVATE = 4
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_DWMWA_CLOAKED = 14
_VK_LBUTTON = 0x01
_GA_ROOT = 2
_CROSVM_CLASS = "CROSVM_1"

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
            u.EnumChildWindows.argtypes = [hwnd, _WNDENUMPROC, wintypes.LPARAM]
            u.GetClassNameW.argtypes = [hwnd, wintypes.LPWSTR, ctypes.c_int]
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
            u.GetForegroundWindow.restype, u.GetForegroundWindow.argtypes = hwnd, []
            u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
            u.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
            u.ShowWindow.argtypes = [hwnd, ctypes.c_int]
            u.GetAsyncKeyState.restype, u.GetAsyncKeyState.argtypes = ctypes.c_short, [ctypes.c_int]
            u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            u.ScreenToClient.argtypes = [hwnd, ctypes.POINTER(wintypes.POINT)]
            u.WindowFromPoint.restype, u.WindowFromPoint.argtypes = hwnd, [wintypes.POINT]
            u.GetAncestor.restype, u.GetAncestor.argtypes = hwnd, [hwnd, wintypes.UINT]
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
            """Post to the emulator surface without focusing or moving the real cursor."""
            if self.is_minimized(hwnd):
                self.restore(hwnd)
                time.sleep(0.15)
            root_width, root_height = self.client_size(hwnd)
            if not (0 <= x < root_width and 0 <= y < root_height):
                raise OSError(f"click coordinate ({x}, {y}) is outside the game client area")
            child = self._find_emulator_surface(hwnd)
            point = wintypes.POINT(x, y)
            if not self._u.ClientToScreen(hwnd, ctypes.byref(point)):
                raise self._last_win32_error("could not map game coordinates to screen")
            if not self._u.ScreenToClient(child, ctypes.byref(point)):
                raise self._last_win32_error("could not map screen coordinates to emulator surface")
            child_width, child_height = self.client_size(child)
            if not (0 <= point.x < child_width and 0 <= point.y < child_height):
                raise OSError("click coordinate falls outside the emulator surface")
            lparam = ((point.y & 0xFFFF) << 16) | (point.x & 0xFFFF)
            if not self._u.PostMessageW(child, _WM_LBUTTONDOWN, _MK_LBUTTON, lparam):
                raise self._last_win32_error("could not post mouse-down to emulator surface")
            time.sleep(0.05)
            if not self._u.PostMessageW(child, _WM_LBUTTONUP, 0, lparam):
                raise self._last_win32_error("could not post mouse-up to emulator surface")

        def _last_win32_error(self, message: str) -> OSError:
            code = ctypes.get_last_error()
            return OSError(code, message)

        def _find_emulator_surface(self, hwnd: int) -> int:
            matches: List[int] = []

            def callback(child, _lparam):
                name = ctypes.create_unicode_buffer(256)
                if self._u.GetClassNameW(child, name, len(name)) and name.value == _CROSVM_CLASS:
                    matches.append(child)
                return True

            self._u.EnumChildWindows(hwnd, _WNDENUMPROC(callback), 0)
            if len(matches) != 1:
                state = "not found" if not matches else "ambiguous"
                raise OSError(f"emulator surface window {state}; refusing background click")
            return matches[0]

        def _click_foreground(self, hwnd: int, x: int, y: int) -> None:
            """Legacy real-input mode: raises the window and moves the actual cursor."""
            if self.is_minimized(hwnd):
                self.restore(hwnd)
                time.sleep(0.5)
            width, height = self.client_size(hwnd)
            if not (0 <= x < width and 0 <= y < height):
                raise OSError(f"click coordinate ({x}, {y}) is outside the game client area")
            origin = wintypes.POINT(0, 0)
            if not self._u.ClientToScreen(hwnd, ctypes.byref(origin)):
                raise self._last_win32_error("could not map game coordinates to screen")
            if not self._u.SetForegroundWindow(hwnd):
                raise self._last_win32_error("Windows refused to focus the game window")
            time.sleep(0.3)
            target = wintypes.POINT(origin.x + x, origin.y + y)
            if self._u.GetAncestor(self._u.GetForegroundWindow(), _GA_ROOT) != hwnd:
                raise OSError("game window did not receive focus; refusing to move cursor")
            if self._u.GetAncestor(self._u.WindowFromPoint(target), _GA_ROOT) != hwnd:
                raise OSError("game window does not own the click location; refusing to move cursor")
            if not self._u.SetCursorPos(target.x, target.y):
                raise self._last_win32_error("could not move cursor to game window")
            # Recheck after cursor movement; focus and ownership can change while we wait.
            if self._u.GetAncestor(self._u.GetForegroundWindow(), _GA_ROOT) != hwnd:
                raise OSError("game window lost focus; refusing foreground click")
            hit = self._u.GetAncestor(self._u.WindowFromPoint(target), _GA_ROOT)
            if hit != hwnd:
                raise OSError("game window does not own the click location; refusing foreground click")
            actual = wintypes.POINT()
            if not self._u.GetCursorPos(ctypes.byref(actual)):
                raise self._last_win32_error("could not verify cursor location")
            if (actual.x, actual.y) != (target.x, target.y):
                raise OSError("cursor moved away from the game click location; refusing foreground click")
            self._u.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            self._u.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

        # -- window state ------------------------------------------------------

        def minimize(self, hwnd: int) -> None:
            self._u.ShowWindow(hwnd, _SW_SHOWMINNOACTIVE)

        def restore(self, hwnd: int) -> None:
            # Lowering an active window with NOACTIVATE does not release focus.
            # Let Windows select the next window before restoring behind it.
            if self._u.GetAncestor(self._u.GetForegroundWindow(), _GA_ROOT) == hwnd:
                self._u.ShowWindow(hwnd, _SW_MINIMIZE)
            self._u.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
            if not self._u.SetWindowPos(hwnd, 1, 0, 0, 0, 0,
                                        _SWP_NOACTIVATE | _SWP_NOMOVE | _SWP_NOSIZE):
                raise self._last_win32_error("could not restore game window without activating it")
            if self.is_minimized(hwnd):
                raise OSError("game window remained minimized after restore")

        def is_minimized(self, hwnd: int) -> bool:
            return bool(self._u.IsIconic(hwnd))

        # -- recording ---------------------------------------------------------

        def poll_input(self, hwnd: int, stop_vk: int) -> InputSample:
            """Polled instead of hooked: no message loop, no extra threads, no dependencies."""
            point = wintypes.POINT()
            self._u.GetCursorPos(ctypes.byref(point))
            # The root-window check keeps clicks that land on a window covering the game out.
            over_window = self._u.GetAncestor(self._u.WindowFromPoint(point), _GA_ROOT) == hwnd
            self._u.ScreenToClient(hwnd, ctypes.byref(point))
            width, height = self.client_size(hwnd)
            inside = bool(over_window) and 0 <= point.x < width and 0 <= point.y < height
            left_down = bool(self._u.GetAsyncKeyState(_VK_LBUTTON) & 0x8000)
            stop = bool(stop_vk) and bool(self._u.GetAsyncKeyState(stop_vk) & 0x8000)
            return InputSample(point.x, point.y, inside, left_down, stop)

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
            raise OSError("league-bot controls Google Play Games for PC and only runs on Windows")
