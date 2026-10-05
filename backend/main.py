from __future__ import annotations

import ipaddress
import json
import os
import socket
import sqlite3
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


app = FastAPI(
    title="SentinelLab",
    version="0.4.0",
)


PROJECT_DIR = Path(__file__).resolve().parent.parent

FRONTEND_FILE = (
    PROJECT_DIR
    / "frontend"
    / "index.html"
)

COLLECTOR_FILE = (
    PROJECT_DIR
    / "collector"
    / "build"
    / "network_collector"
)

DATA_DIR = PROJECT_DIR / "data"
DATABASE_FILE = DATA_DIR / "sentinellab.db"
ALERT_SCAN_LOCK = threading.Lock()


def load_approved_lan_ports() -> dict[int, str]:
    """Load deployment-local PORT=LABEL entries from the environment."""
    raw_value = os.getenv("SENTINELLAB_APPROVED_LAN_PORTS", "")
    approved: dict[int, str] = {}

    for raw_entry in raw_value.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue

        port_text, separator, label = entry.partition("=")
        if not separator:
            raise RuntimeError(
                "SENTINELLAB_APPROVED_LAN_PORTS entries must use PORT=LABEL"
            )

        try:
            port = int(port_text.strip())
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid approved port: {port_text!r}"
            ) from exc

        label = label.strip()
        if not 1 <= port <= 65535:
            raise RuntimeError(f"Approved port is out of range: {port}")

        if not label:
            raise RuntimeError(f"Approved port {port} requires a label")

        approved[port] = label

    return approved


APPROVED_LAN_PORTS = load_approved_lan_ports()


def utc_now() -> str:
    """Return the current time in UTC."""
    return datetime.now(timezone.utc).isoformat()


def initialize_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(DATA_DIR, 0o700)

    with sqlite3.connect(DATABASE_FILE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                port INTEGER NOT NULL,
                address TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        connection.commit()

    os.chmod(DATABASE_FILE, 0o600)


def run_network_collector() -> dict[str, int | str]:
    if not COLLECTOR_FILE.is_file():
        raise RuntimeError("The compiled network collector is missing")

    try:
        completed = subprocess.run(
            [str(COLLECTOR_FILE)],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The network collector timed out") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("The network collector failed") from exc

    try:
        payload = json.loads(completed.stdout)
        bytes_received = int(payload["bytes_received"])
        bytes_sent = int(payload["bytes_sent"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("The network collector returned invalid JSON") from exc

    if bytes_received < 0 or bytes_sent < 0:
        raise RuntimeError("The network collector returned negative counters")

    return {
        "bytes_received": bytes_received,
        "bytes_sent": bytes_sent,
        "source": str(payload.get("source", "cpp")),
    }


def get_tcp_connections() -> list[psutil._common.sconn]:
    try:
        return psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, PermissionError, OSError) as exc:
        raise RuntimeError("TCP connection information is unavailable") from exc


def count_established_tcp_connections() -> int:
    return sum(
        1
        for connection in get_tcp_connections()
        if connection.status == psutil.CONN_ESTABLISHED
    )


def get_listening_ports_snapshot() -> list[dict[str, int | str | None]]:
    listeners: list[dict[str, int | str | None]] = []
    seen: set[tuple[str, int, int | None]] = set()

    for connection in get_tcp_connections():
        if connection.status != psutil.CONN_LISTEN or not connection.laddr:
            continue

        address = str(connection.laddr.ip)
        port = int(connection.laddr.port)
        pid = connection.pid
        key = (address, port, pid)

        if key in seen:
            continue

        seen.add(key)
        listeners.append(
            {
                "address": address,
                "port": port,
                "pid": pid,
            }
        )

    listeners.sort(
        key=lambda listener: (
            int(listener["port"]),
            str(listener["address"]),
            -1 if listener["pid"] is None else int(listener["pid"]),
        )
    )
    return listeners


def is_loopback_address(address: str) -> bool:
    normalized = address.split("%", 1)[0]

    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return address.startswith("127.") or address == "::1"


def _address_preference(address: str) -> tuple[int, str]:
    if address == "0.0.0.0":
        return (0, address)
    if address == "::":
        return (1, address)
    return (2, address)


def detect_alerts(
    listeners: list[dict[str, int | str | None]],
) -> list[dict[str, int | str]]:
    unexpected_by_port: dict[int, str] = {}

    for listener in listeners:
        address = str(listener["address"])
        port = int(listener["port"])

        if is_loopback_address(address) or port in APPROVED_LAN_PORTS:
            continue

        previous_address = unexpected_by_port.get(port)
        if (
            previous_address is None
            or _address_preference(address)
            < _address_preference(previous_address)
        ):
            unexpected_by_port[port] = address

    alerts: list[dict[str, int | str]] = []

    for port in sorted(unexpected_by_port):
        address = unexpected_by_port[port]
        alerts.append(
            {
                "id": f"unexpected-port-{port}",
                "severity": "warning",
                "title": "Unexpected LAN-exposed port",
                "description": (
                    f"TCP port {port} is listening on {address} "
                    "and is not approved."
                ),
                "port": port,
                "address": address,
            }
        )

    return alerts


def update_alert_history(alerts: list[dict[str, int | str]]) -> None:
    observed_at = utc_now()

    with sqlite3.connect(DATABASE_FILE) as connection:
        connection.execute(
            "UPDATE alert_history SET active = 0 WHERE active = 1"
        )

        for alert in alerts:
            connection.execute(
                """
                INSERT INTO alert_history (
                    fingerprint,
                    severity,
                    title,
                    description,
                    port,
                    address,
                    first_seen,
                    last_seen,
                    active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    severity = excluded.severity,
                    title = excluded.title,
                    description = excluded.description,
                    port = excluded.port,
                    address = excluded.address,
                    last_seen = excluded.last_seen,
                    active = 1
                """,
                (
                    alert["id"],
                    alert["severity"],
                    alert["title"],
                    alert["description"],
                    alert["port"],
                    alert["address"],
                    observed_at,
                    observed_at,
                ),
            )

        connection.commit()


def read_alert_history() -> list[dict[str, int | str | bool]]:
    with sqlite3.connect(DATABASE_FILE) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                fingerprint,
                severity,
                title,
                description,
                port,
                address,
                first_seen,
                last_seen,
                active
            FROM alert_history
            ORDER BY active DESC, last_seen DESC
            LIMIT 100
            """
        ).fetchall()

    return [
        {
            "id": str(row["fingerprint"]),
            "severity": str(row["severity"]),
            "title": str(row["title"]),
            "description": str(row["description"]),
            "port": int(row["port"]),
            "address": str(row["address"]),
            "first_seen": str(row["first_seen"]),
            "last_seen": str(row["last_seen"]),
            "active": bool(row["active"]),
        }
        for row in rows
    ]


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/")
def get_dashboard() -> FileResponse:
    if not FRONTEND_FILE.is_file():
        raise HTTPException(status_code=404, detail="Dashboard file not found")

    return FileResponse(FRONTEND_FILE)


@app.get("/api/status")
def get_status() -> dict[str, int | str]:
    try:
        collector = run_network_collector()
        active_connections = count_established_tcp_connections()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "hostname": socket.gethostname(),
        "bytes_received": int(collector["bytes_received"]),
        "bytes_sent": int(collector["bytes_sent"]),
        "active_connections": active_connections,
        "network_source": str(collector["source"]),
    }


@app.get("/api/listening-ports")
def get_listening_ports() -> dict[str, object]:
    try:
        listeners = get_listening_ports_snapshot()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "count": len(listeners),
        "ports": listeners,
    }


@app.get("/api/alerts")
def get_alerts() -> dict[str, object]:
    try:
        with ALERT_SCAN_LOCK:
            listeners = get_listening_ports_snapshot()
            alerts = detect_alerts(listeners)
            update_alert_history(alerts)
    except (RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=503,
            detail="Alert scanning is temporarily unavailable",
        ) from exc

    return {
        "count": len(alerts),
        "alerts": alerts,
    }


@app.get("/api/alert-history")
def get_alert_history() -> dict[str, object]:
    try:
        events = read_alert_history()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail="Alert history is temporarily unavailable",
        ) from exc

    return {
        "count": len(events),
        "events": events,
    }
