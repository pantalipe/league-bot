import ctypes
import unittest
from unittest.mock import Mock, patch

from league_bot import winapi


@unittest.skipUnless(winapi.IS_WINDOWS, "Win32 API tests require Windows")
class Win32InputMockTests(unittest.TestCase):
    ROOT, CHILD = 10, 20

    def setUp(self):
        self.backend = winapi.Win32Backend.__new__(winapi.Win32Backend)
        self.sizes = {self.ROOT: (500, 400), self.CHILD: (400, 300)}
        self.children = [self.CHILD]
        self.class_names = {self.CHILD: "CROSVM_1"}
        self.u = Mock()

        def get_client_rect(hwnd, rect_ptr):
            rect = ctypes.cast(rect_ptr, ctypes.POINTER(ctypes.wintypes.RECT)).contents
            rect.left = rect.top = 0
            rect.right, rect.bottom = self.sizes[hwnd]
            return 1

        def enum_children(hwnd, callback, _param):
            for child in self.children:
                callback(child, 0)
            return 1

        def get_class_name(hwnd, buf, _length):
            buf.value = self.class_names.get(hwnd, "")
            return len(buf.value)

        def client_to_screen(_hwnd, point_ptr):
            point = ctypes.cast(point_ptr, ctypes.POINTER(ctypes.wintypes.POINT)).contents
            point.x += 100
            point.y += 200
            return 1

        def screen_to_client(hwnd, point_ptr):
            point = ctypes.cast(point_ptr, ctypes.POINTER(ctypes.wintypes.POINT)).contents
            point.x -= 90 if hwnd == self.CHILD else 100
            point.y -= 180 if hwnd == self.CHILD else 200
            return 1

        self.u.GetClientRect.side_effect = get_client_rect
        self.u.EnumChildWindows.side_effect = enum_children
        self.u.GetClassNameW.side_effect = get_class_name
        self.u.ClientToScreen.side_effect = client_to_screen
        self.u.ScreenToClient.side_effect = screen_to_client
        self.backend._u = self.u
        self.backend._d = Mock()
        self.backend.is_minimized = Mock(return_value=False)

    def enable_windows_symbols(self):
        return patch.multiple(winapi, ctypes=ctypes, wintypes=ctypes.wintypes)

    def test_background_click_routes_offset_coordinates_to_dynamic_child(self):
        with self.enable_windows_symbols(), patch.object(winapi.time, "sleep"):
            self.backend.click(self.ROOT, 30, 40, False)
            self.assertEqual(self.u.PostMessageW.call_args_list[0].args,
                             (self.CHILD, winapi._WM_LBUTTONDOWN, winapi._MK_LBUTTON, (60 << 16) | 40))
            self.assertEqual(self.u.PostMessageW.call_args_list[1].args,
                             (self.CHILD, winapi._WM_LBUTTONUP, 0, (60 << 16) | 40))
            self.assert_not_called(self.u.SetForegroundWindow)
            self.assert_not_called(self.u.SetCursorPos)

    def test_minimized_background_click_restores_before_measuring_and_posting(self):
        with self.enable_windows_symbols(), patch.object(winapi.time, "sleep") as sleep:
            self.backend.is_minimized.side_effect = [True, False]
            self.u.SetWindowPos.return_value = 1
            self.backend.click(self.ROOT, 30, 40, False)
            self.assertEqual(self.u.ShowWindow.call_args.args,
                             (self.ROOT, winapi._SW_SHOWNOACTIVATE))
            self.assertEqual(self.u.SetWindowPos.call_args.args[0], self.ROOT)
            self.assertEqual(self.u.PostMessageW.call_args_list[0].args[0], self.CHILD)
            self.assertIn(unittest.mock.call(0.15), sleep.call_args_list)

    def test_minimized_background_click_restore_failure_never_posts(self):
        with self.enable_windows_symbols(), patch.object(winapi.time, "sleep"):
            self.backend.is_minimized.side_effect = [True, True]
            self.u.SetWindowPos.return_value = 1
            with self.assertRaises(OSError):
                self.backend.click(self.ROOT, 30, 40, False)
            self.assert_not_called(self.u.PostMessageW)

    def test_child_is_looked_up_again_for_each_click(self):
        with self.enable_windows_symbols(), patch.object(winapi.time, "sleep"):
            self.backend.click(self.ROOT, 30, 40, False)
            self.children = [21]
            self.sizes[21] = (500, 400)
            self.class_names[21] = "CROSVM_1"
            self.backend.click(self.ROOT, 30, 40, False)
            self.assertEqual(self.u.PostMessageW.call_args_list[2].args[0], 21)

    def test_missing_or_ambiguous_surface_fails_without_posting(self):
        with self.enable_windows_symbols():
            for children in ([], [20, 21]):
                self.children = children
                self.class_names[21] = "CROSVM_1"
                with self.assertRaises(OSError):
                    self.backend.click(self.ROOT, 1, 1, False)
            self.assert_not_called(self.u.PostMessageW)

    def test_out_of_bounds_and_postmessage_errors_fail_closed(self):
        with self.enable_windows_symbols(), patch.object(winapi.time, "sleep"):
            with self.assertRaises(OSError):
                self.backend.click(self.ROOT, 500, 0, False)
            self.u.PostMessageW.return_value = 0
            with patch.object(ctypes, "get_last_error", return_value=5, create=True):
                with self.assertRaises(OSError):
                    self.backend.click(self.ROOT, 1, 1, False)
            self.assertEqual(self.u.PostMessageW.call_count, 1)

    def test_child_bounds_and_coordinate_mapping_failures_fail_closed(self):
        with self.enable_windows_symbols():
            self.u.ScreenToClient.side_effect = None
            self.u.ScreenToClient.return_value = 0
            with self.assertRaises(OSError):
                self.backend.click(self.ROOT, 1, 1, False)
            self.u.ScreenToClient.return_value = 1
            self.u.ScreenToClient.side_effect = lambda hwnd, ptr: self._screen_to_client(hwnd, ptr)
            self.u.GetClientRect.side_effect = lambda hwnd, ptr: self._set_rect(
                hwnd, ptr, (500, 400) if hwnd == self.ROOT else (10, 10))
            with self.assertRaises(OSError):
                self.backend.click(self.ROOT, 30, 40, False)
            self.assert_not_called(self.u.PostMessageW)

    @staticmethod
    def _set_rect(hwnd, rect_ptr, size):
        rect = ctypes.cast(rect_ptr, ctypes.POINTER(ctypes.wintypes.RECT)).contents
        rect.left = rect.top = 0
        rect.right, rect.bottom = size
        return 1

    def test_mouse_up_post_failure_is_reported(self):
        with self.enable_windows_symbols(), patch.object(winapi.time, "sleep"):
            self.u.PostMessageW.side_effect = [1, 0]
            with patch.object(ctypes, "get_last_error", return_value=5, create=True):
                with self.assertRaises(OSError):
                    self.backend.click(self.ROOT, 1, 1, False)
            self.assertEqual(self.u.PostMessageW.call_count, 2)

    def test_foreground_focus_rejection_prevents_cursor_or_click(self):
        with self.enable_windows_symbols(), patch.object(winapi.time, "sleep"):
            self._prepare_foreground_click()
            self.u.GetForegroundWindow.return_value = 99
            with self.assertRaises(OSError):
                self.backend.click(self.ROOT, 1, 1, True)
            self.assert_not_called(self.u.SetCursorPos)
            self.assert_not_called(self.u.mouse_event)

    def test_foreground_coordinate_and_cursor_api_failures_prevent_click(self):
        with self.enable_windows_symbols(), patch.object(winapi.time, "sleep"):
            self._prepare_foreground_click()
            self.u.ClientToScreen.side_effect = None
            self.u.ClientToScreen.return_value = 0
            with patch.object(ctypes, "get_last_error", return_value=5, create=True):
                with self.assertRaises(OSError):
                    self.backend.click(self.ROOT, 1, 1, True)
            self.assert_not_called(self.u.SetForegroundWindow)

            self.u.ClientToScreen.side_effect = lambda _hwnd, ptr: self._set_origin(ptr)
            self.u.SetCursorPos.return_value = 0
            with patch.object(ctypes, "get_last_error", return_value=5, create=True):
                with self.assertRaises(OSError):
                    self.backend.click(self.ROOT, 1, 1, True)
            self.assert_not_called(self.u.mouse_event)

    @staticmethod
    def _set_origin(ptr):
        point = ctypes.cast(ptr, ctypes.POINTER(ctypes.wintypes.POINT)).contents
        point.x, point.y = 100, 200
        return 1

    @staticmethod
    def _screen_to_client(hwnd, ptr):
        point = ctypes.cast(ptr, ctypes.POINTER(ctypes.wintypes.POINT)).contents
        point.x -= 90 if hwnd == Win32InputMockTests.CHILD else 100
        point.y -= 180 if hwnd == Win32InputMockTests.CHILD else 200
        return 1

    def _prepare_foreground_click(self):
        self.backend.client_size = Mock(return_value=(500, 400))
        self.backend.is_minimized = Mock(return_value=False)
        self.u.ClientToScreen.side_effect = lambda _hwnd, ptr: self._set_origin(ptr)
        self.u.SetForegroundWindow.return_value = 1
        self.u.SetCursorPos.return_value = 1
        self.u.GetForegroundWindow.return_value = self.ROOT
        self.u.GetAncestor.side_effect = lambda hwnd, _flag: hwnd
        self.u.WindowFromPoint.return_value = self.ROOT

        def get_cursor(point_ptr):
            point = ctypes.cast(point_ptr, ctypes.POINTER(ctypes.wintypes.POINT)).contents
            point.x, point.y = 101, 201
            return 1

        self.u.GetCursorPos.side_effect = get_cursor

    def test_foreground_set_failure_blocked_hit_and_post_move_focus_loss_prevent_down(self):
        with self.enable_windows_symbols(), patch.object(winapi.time, "sleep"):
            self._prepare_foreground_click()
            self.u.SetForegroundWindow.return_value = 0
            with patch.object(ctypes, "get_last_error", return_value=5, create=True):
                with self.assertRaises(OSError):
                    self.backend.click(self.ROOT, 1, 1, True)
            self.assert_not_called(self.u.SetCursorPos)

            self.u.SetForegroundWindow.return_value = 1
            self.u.WindowFromPoint.return_value = 99
            with self.assertRaises(OSError):
                self.backend.click(self.ROOT, 1, 1, True)
            self.assert_not_called(self.u.mouse_event)

            self.u.WindowFromPoint.return_value = self.ROOT
            self.u.GetForegroundWindow.side_effect = [self.ROOT, 99]
            with self.assertRaises(OSError):
                self.backend.click(self.ROOT, 1, 1, True)
            self.assert_not_called(self.u.mouse_event)

    def test_foreground_click_rejects_out_of_bounds_and_succeeds_when_verified(self):
        with self.enable_windows_symbols(), patch.object(winapi.time, "sleep"):
            self._prepare_foreground_click()
            with self.assertRaises(OSError):
                self.backend.click(self.ROOT, 500, 0, True)
            self.assert_not_called(self.u.SetForegroundWindow)

            self.u.GetCursorPos.side_effect = lambda ptr: self._copy_expected_cursor(ptr)
            self.backend.click(self.ROOT, 1, 1, True)
            self.assertEqual(self.u.mouse_event.call_count, 2)

    @staticmethod
    def _copy_expected_cursor(ptr):
        point = ctypes.cast(ptr, ctypes.POINTER(ctypes.wintypes.POINT)).contents
        point.x, point.y = 101, 201
        return 1

    def test_restore_and_minimize_use_nonactivating_commands(self):
        with self.enable_windows_symbols():
            self.u.SetWindowPos.return_value = 1
            self.backend.is_minimized = Mock(return_value=False)
            self.backend.restore(self.ROOT)
            self.assertEqual(self.u.ShowWindow.call_args.args, (self.ROOT, winapi._SW_SHOWNOACTIVATE))
            self.assertEqual(self.u.SetWindowPos.call_args.args[-1],
                             winapi._SWP_NOACTIVATE | winapi._SWP_NOMOVE | winapi._SWP_NOSIZE)
            self.backend.minimize(self.ROOT)
            self.assertEqual(self.u.ShowWindow.call_args.args, (self.ROOT, winapi._SW_SHOWMINNOACTIVE))

    def test_restore_fails_if_window_remains_minimized(self):
        with self.enable_windows_symbols():
            self.u.SetWindowPos.return_value = 1
            self.backend.is_minimized = Mock(return_value=True)
            with self.assertRaises(OSError):
                self.backend.restore(self.ROOT)

    @staticmethod
    def assert_not_called(mock):
        if mock.called:
            raise AssertionError(f"expected {mock!r} not to be called")


if __name__ == "__main__":
    unittest.main()
