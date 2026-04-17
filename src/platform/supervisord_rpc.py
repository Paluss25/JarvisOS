"""Supervisor XML-RPC client — start/stop/restart/status via Unix socket."""

import logging
import xmlrpc.client
from http.client import HTTPConnection
from socket import socket, AF_UNIX, SOCK_STREAM

logger = logging.getLogger(__name__)

_SOCKET_PATH = "/var/run/supervisor.sock"


class _UnixStreamTransport(xmlrpc.client.Transport):
    """Transport that connects over a Unix domain socket."""

    def __init__(self, socket_path: str):
        super().__init__()
        self._socket_path = socket_path

    def make_connection(self, host):
        conn = _UnixSocketConnection(self._socket_path)
        return conn


class _UnixSocketConnection(HTTPConnection):
    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self):
        sock = socket(AF_UNIX, SOCK_STREAM)
        sock.connect(self._socket_path)
        self.sock = sock


class SupervisorClient:
    """Wrapper around supervisor XML-RPC API via Unix socket."""

    def _proxy(self):
        transport = _UnixStreamTransport(_SOCKET_PATH)
        return xmlrpc.client.ServerProxy("http://localhost", transport=transport)

    def get_all_process_info(self) -> list[dict]:
        return self._proxy().supervisor.getAllProcessInfo()

    def get_process_info(self, name: str) -> dict:
        return self._proxy().supervisor.getProcessInfo(name)

    def start_process(self, name: str) -> bool:
        return self._proxy().supervisor.startProcess(name)

    def stop_process(self, name: str) -> bool:
        return self._proxy().supervisor.stopProcess(name)

    def restart_process(self, name: str) -> bool:
        self.stop_process(name)
        return self.start_process(name)

    def reread(self) -> list:
        return self._proxy().supervisor.reloadConfig()

    def update(self) -> list:
        return self._proxy().supervisor.reloadConfig()
