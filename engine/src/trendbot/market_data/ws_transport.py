"""Async WebSocket transport abstraction.

The live feed depends on this protocol, never on the ``websockets``
library directly, so scripted transports drive every test offline. The
real transport adapts the ``websockets`` library (imported lazily) and
maps library closures to the transport-agnostic :class:`WsConnectionLost`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable


class WsConnectionLost(Exception):
    """The WebSocket connection ended (cleanly or not)."""

    def __init__(self, detail: str = "connection closed") -> None:
        super().__init__(detail)


@runtime_checkable
class WsConnection(Protocol):
    async def send(self, text: str) -> None: ...

    async def recv(self) -> str:
        """Return the next frame; raises WsConnectionLost when closed."""
        ...

    async def close(self) -> None: ...


TransportFactory = Callable[[], Awaitable["WsConnection"]]


class WebsocketsTransportFactory:
    """Real transport factory built on the ``websockets`` library.

    Imported lazily so environments without a running loop never load it
    at import time. Library-level failures map to the transport-agnostic
    :class:`WsConnectionLost`.
    """

    def __init__(self, url: str) -> None:
        self.url = url

    async def __call__(self) -> WsConnection:
        import websockets

        try:
            connection = await websockets.connect(self.url, open_timeout=10)
        except Exception as exc:  # noqa: BLE001 - normalized per transport contract
            raise WsConnectionLost(f"could not connect to {self.url}: {exc}") from exc
        return _WebsocketsConnection(connection)


def websockets_transport_factory(url: str) -> TransportFactory:
    return WebsocketsTransportFactory(url)


class _WebsocketsConnection:
    def __init__(self, connection: object) -> None:
        self._connection = connection

    async def send(self, text: str) -> None:
        await self._connection.send(text)  # type: ignore[attr-defined]

    async def recv(self) -> str:
        try:
            return await self._connection.recv()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - any library closure = connection lost
            raise WsConnectionLost(str(exc)) from exc

    async def close(self) -> None:
        try:
            await self._connection.close()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - best effort
            pass
