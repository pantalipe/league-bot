"""The interface between the macro engine / game controller and the OS window layer."""
from __future__ import annotations

from typing import List, Optional, Protocol, Tuple

from .imaging import Frame


class Backend(Protocol):
    """Everything the rest of the code needs from the operating system.

    ``winapi.Win32Backend`` is the real implementation; tests use a fake one.
    Window handles are opaque ints. Coordinates are relative to the window's
    client area -- the same space as the frames returned by ``capture``.
    """

    def list_windows(self) -> List[str]:
        """Titles of visible top-level windows."""

    def find_window(self, title: str) -> Optional[int]:
        """Handle of the window whose title matches (exact first, then substring)."""

    def is_window(self, hwnd: int) -> bool: ...

    def client_size(self, hwnd: int) -> Tuple[int, int]: ...

    def capture(self, hwnd: int) -> Optional[Frame]:
        """Grab the window content without bringing it to the front."""

    def click(self, hwnd: int, x: int, y: int, foreground: bool) -> None:
        """Left click at client coordinates (real mouse when ``foreground``)."""

    def minimize(self, hwnd: int) -> None: ...

    def restore(self, hwnd: int) -> None: ...

    def is_minimized(self, hwnd: int) -> bool: ...

    def move_resize(self, hwnd: int, x: Optional[int], y: Optional[int], width: int, height: int) -> None:
        """Move/resize in screen coordinates; ``None`` for x/y keeps the current position."""
