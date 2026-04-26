"""
WebSocket-Verbindungsverwaltung für HausRadar.

Der ConnectionManager hält alle aktiven Browser-Verbindungen und
sendet bei jedem neuen Bewegungsdatensatz ein Update an alle.
Fehlerhafte Verbindungen werden automatisch entfernt.
"""

import logging
from typing import List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: List[WebSocket] = []
        self._max_connections: int = 20

    def set_max_connections(self, max_conn: int) -> None:
        self._max_connections = max_conn

    async def connect(self, websocket: WebSocket) -> bool:
        """Akzeptiert die Verbindung. Gibt False zurück wenn Limit erreicht."""
        if len(self._connections) >= self._max_connections:
            await websocket.close(code=1008)
            logger.warning(
                "WebSocket abgelehnt – Verbindungslimit erreicht (%d)", self._max_connections
            )
            return False
        await websocket.accept()
        self._connections.append(websocket)
        logger.info(
            "WebSocket verbunden (total: %d)", len(self._connections)
        )
        return True

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)
        logger.info(
            "WebSocket getrennt (total: %d)", len(self._connections)
        )

    async def broadcast(self, data: dict) -> None:
        """Sendet data als JSON an alle verbundenen Clients.

        Clients, die beim Senden einen Fehler erzeugen, werden
        stillschweigend entfernt – sie dürfen den Server nicht crashen.
        """
        dead: List[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(data)
            except Exception as exc:
                logger.warning(
                    "WebSocket-Sendefehler, entferne Verbindung: %s", exc
                )
                dead.append(ws)
        for ws in dead:
            if ws in self._connections:
                self._connections.remove(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Globale Instanz – wird von motion.py und main.py gemeinsam genutzt
manager = ConnectionManager()
