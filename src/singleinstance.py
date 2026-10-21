# -*- coding: utf-8 -*-
"""
ClickTask - singleinstance.py
Description: One GUI per session. The first process binds a Unix socket under
             $XDG_RUNTIME_DIR/clicktask; the next one connects to it, asks the
             running window to come forward and exits. Stale sockets (a crash
             without cleanup) are detected and replaced.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import errno
import os
import socket
import threading

SOCKET_NAME = "clicktask-gui.sock"
RAISE = b"raise\n"


def runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base and os.path.isabs(base):
        return os.path.join(base, "clicktask")
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return os.path.join(cache, "clicktask")


def socket_path():
    return os.path.join(runtime_dir(), SOCKET_NAME)


class SingleInstance:
    """Bind once, then accept raise requests until `release()`."""

    def __init__(self, path=None):
        self.path = path or socket_path()
        self._socket = None
        self._thread = None
        self._running = threading.Event()
        self._owned = False

    def acquire(self):
        """Return True when this process owns the app, False if one is running."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        except OSError:
            return True  # no runtime dir: never block the GUI over bookkeeping

        for attempt in (1, 2):
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(self.path)
            except OSError as exc:
                server.close()
                if exc.errno not in (errno.EADDRINUSE, errno.EEXIST):
                    return True
                if self.request_raise():
                    return False
                if attempt == 2:
                    return True
                try:
                    os.unlink(self.path)  # stale socket from a crashed run
                except OSError:
                    return True
                continue
            try:
                os.chmod(self.path, 0o600)
                server.listen(4)
            except OSError:
                server.close()
                return True
            self._socket = server
            self._owned = True
            return True
        return True

    def listen(self, callback):
        """Start accepting raise requests; `callback` runs in this thread."""
        if self._socket is None or self._thread is not None:
            return False
        self._running.set()
        self._thread = threading.Thread(
            target=self._serve, args=(callback,), name="clicktask-ipc", daemon=True
        )
        self._thread.start()
        return True

    def _serve(self, callback):
        while self._running.is_set() and self._socket is not None:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            with connection:
                try:
                    message = connection.recv(64)
                except OSError:
                    continue
            if message.strip() == RAISE.strip():
                try:
                    callback()
                except Exception:  # a failing callback must not kill the app
                    pass

    def request_raise(self):
        """Ask the running instance to show its window. False when nobody listens."""
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(1.0)
        try:
            client.connect(self.path)
            client.sendall(RAISE)
        except OSError:
            return False
        finally:
            client.close()
        return True

    def release(self):
        if not self._owned:
            return
        self._running.clear()
        server, self._socket = self._socket, None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        try:
            os.unlink(self.path)
        except OSError:
            pass
        self._owned = False
