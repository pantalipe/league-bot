"""The interface between the macro engine / game controller and the OS window layer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, ContextManager, List, Optional, Protocol, Tuple

from .imaging import Frame


@dataclass(frozen=True)
class InputSample:
    """One reading of the mouse and a stop key, relative to a window.

    ``x``/``y`` are client coordinates; ``inside`` says the cursor is over that
    window (not covered by another one); ``left_down`` is the state of the left
    button; ``stop_pressed`` says whether the requested stop key is held down.
    """

    x: int
    y: int
    inside: bool
    left_down: bool
    stop_pressed: bool = False


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

    def poll_input(self, hwnd: int, stop_vk: int) -> InputSample:
        """Read the mouse (client coordinates), the left button and the ``stop_vk`` key now."""


class GuardedBackend:
    """Wraps a Backend so real mouse clicks run inside ``guard()``.

    A host application can use this to lift its own keyboard/mouse lock only for the
    instant of each click. Everything else is forwarded untouched.
    """

    def __init__(self, inner: Backend, guard: Callable[[], ContextManager[Any]]) -> None:
        self._inner = inner
        self._guard = guard

    def click(self, hwnd: int, x: int, y: int, foreground: bool) -> None:
        if foreground:
            with self._guard():
                self._inner.click(hwnd, x, y, foreground)
        else:
            self._inner.click(hwnd, x, y, foreground)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
