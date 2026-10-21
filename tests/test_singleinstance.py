# -*- coding: utf-8 -*-
"""
ClickTask - test_singleinstance.py
Description: Single-instance tests in a temporary runtime directory: the second
             process cannot take the socket, it can ask the first one to raise
             its window, stale sockets are replaced and release cleans up.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import singleinstance  # noqa: E402


class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.environment = patch.dict(
            os.environ,
            {"XDG_RUNTIME_DIR": self.tmp, "XDG_CACHE_HOME": os.path.join(self.tmp, "cache")},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_first_process_owns_the_socket(self):
        instance = singleinstance.SingleInstance()
        self.assertTrue(instance.acquire())
        self.assertTrue(os.path.exists(singleinstance.socket_path()))
        instance.release()
        self.assertFalse(os.path.exists(singleinstance.socket_path()))

    def test_second_process_is_refused_and_raises_the_first(self):
        first = singleinstance.SingleInstance()
        self.assertTrue(first.acquire())
        raised = threading.Event()
        self.assertTrue(first.listen(raised.set))

        second = singleinstance.SingleInstance()
        self.assertFalse(second.acquire())
        self.assertTrue(raised.wait(2), "the running instance did not receive raise")
        first.release()

    def test_stale_socket_is_replaced(self):
        path = singleinstance.socket_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(path)
        stale.close()  # left behind by a crash: nobody is listening

        instance = singleinstance.SingleInstance()
        self.assertTrue(instance.acquire())
        self.assertTrue(os.path.exists(path))
        instance.release()

    def test_raise_without_a_running_instance_returns_false(self):
        instance = singleinstance.SingleInstance()
        self.assertFalse(instance.request_raise())

    def test_release_from_a_second_object_keeps_the_owner_socket(self):
        first = singleinstance.SingleInstance()
        self.assertTrue(first.acquire())
        second = singleinstance.SingleInstance()
        second.release()
        self.assertTrue(os.path.exists(singleinstance.socket_path()))
        first.release()


if __name__ == "__main__":
    unittest.main()
