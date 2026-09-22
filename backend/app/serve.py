"""Serve the app on the public port and on the private-network port, in one process."""

import asyncio
import socket

import uvicorn

from app.core.config import config


def bind_socket(host: str, port: int) -> socket.socket:
    """Bind host:port, resolving the host first as fly-local-6pn names an IPv6 address."""
    family, _, _, _, address = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(address)
    return sock


def main() -> None:
    server = uvicorn.Server(uvicorn.Config("app.main:app"))
    sockets = [
        bind_socket("0.0.0.0", config.PUBLIC_PORT),
        bind_socket(config.PRIVATE_HOST, config.PRIVATE_PORT),
    ]
    asyncio.run(server.serve(sockets=sockets))
