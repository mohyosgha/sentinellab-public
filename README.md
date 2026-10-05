# SentinelLab

SentinelLab is a defensive, self-hosted network-status and listener-monitoring dashboard for Ubuntu Linux. It combines a small C++ collector, a Python/FastAPI backend, a browser frontend, and SQLite alert history.

The application is designed to remain bound to loopback and be viewed through an SSH tunnel. It does not capture packet contents or expose the dashboard directly to the network.

## Features

- Cumulative received and transmitted byte counters from `/proc/net/dev`.
- Browser-calculated download and upload rates.
- Visible established TCP connection count.
- Visible TCP listening-socket inventory.
- Local-only versus LAN-accessible listener classification.
- Detection of unexpected LAN-accessible ports.
- Persistent active and resolved alert history in SQLite.
- FastAPI interactive API documentation.
- Optional systemd service for automatic startup.
- Deployment-local approved-port configuration kept outside Git.

## Scope

SentinelLab monitors the Linux host on which it runs. An ordinary device connected to a switched network generally cannot observe traffic exchanged exclusively between other devices.

SentinelLab is not:

- A packet sniffer.
- A replacement for a firewall, router, IDS, or SIEM.
- Proof that an unexpected listener is malicious.
- A complete inventory of every socket when the service lacks permission to view another process.

An alert means that a listener should be identified and reviewed.

## Architecture

```text
/proc/net/dev
      |
      v
C++ network_collector
      |
      | JSON
      v
FastAPI backend ----> psutil TCP inspection
      |
      +-------------> SQLite alert history
      |
      | JSON APIs
      v
HTML/CSS/JavaScript dashboard
      |
      | 127.0.0.1:8000
      v
Private SSH tunnel
```

## Repository Layout

```text
backend/main.py             FastAPI API, listener detection, and SQLite
collector/main.cpp          Linux interface-byte collector
collector/CMakeLists.txt    C++17 build configuration
frontend/index.html         Browser dashboard
docs/                       Maintenance and AI handoff documentation
requirements.txt            Python dependencies
```

Generated files such as `.venv/`, `collector/build/`, SQLite databases, caches, and private configuration must remain outside Git.

## Requirements

- Ubuntu Linux or another compatible Linux distribution.
- Python 3.10 or newer.
- A C++17 compiler.
- CMake 3.16 or newer.
- FastAPI, Uvicorn, and psutil from `requirements.txt`.

## Installation

Install system prerequisites:

```bash
sudo apt update
sudo apt install -y build-essential cmake python3-venv git
```

Create the Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Build the C++ collector:

```bash
cmake -S collector -B collector/build
cmake --build collector/build
./collector/build/network_collector
```

The collector should print one JSON object containing `bytes_received`, `bytes_sent`, and `source`.

## Approved Ports

Approved LAN ports are loaded at startup from the optional `SENTINELLAB_APPROVED_LAN_PORTS` environment variable. The public default is empty.

The value is a comma-separated list of `PORT=LABEL` entries:

```text
12345=Example service
```

Keep the real service inventory in private deployment configuration rather than Git. Labels are descriptive text, not a place for passwords, tokens, or other secrets.

The value is validated when the backend starts, so restart the service after changing it.

Do not approve a port merely to silence an alert. Identify its owning process and confirm that the service is intentional first.

## Development Run

Activate the environment and start Uvicorn on loopback:

```bash
source .venv/bin/activate
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Do not run this development server at the same time as the systemd service on port 8000.

Open locally on the server, or create the SSH tunnel described below.

## systemd Deployment

An example service definition is:

```ini
[Unit]
Description=SentinelLab Network Security Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<server-user>
Group=<server-group>
WorkingDirectory=/home/<server-user>/sentinellab
ExecStart=/home/<server-user>/sentinellab/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Replace the angle-bracket placeholders before installing the service. Do not add `--reload` to the production service.

Store approved ports in a private systemd drop-in:

```bash
sudo systemctl edit sentinellab
```

Example drop-in:

```ini
[Service]
Environment="SENTINELLAB_APPROVED_LAN_PORTS=12345=Example service"
UMask=0077
```

Apply and verify changes:

```bash
sudo systemctl daemon-reload
sudo systemctl restart sentinellab
sudo systemctl is-active sentinellab
```

## Private Browser Access

Keep Uvicorn bound to `127.0.0.1`. From a client computer, create an SSH tunnel using deployment-specific values:

```text
ssh -L 8000:127.0.0.1:8000 <server-user>@<server-address>
```

Leave that SSH session open and browse to:

```text
http://localhost:8000
```

Additional local URLs:

```text
http://localhost:8000/docs
http://localhost:8000/api/status
http://localhost:8000/api/listening-ports
http://localhost:8000/api/alerts
http://localhost:8000/api/alert-history
```

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /` | Serve the dashboard. |
| `GET /api/status` | Return byte counters, visible established TCP count, and collector source. |
| `GET /api/listening-ports` | Return visible TCP listening sockets. |
| `GET /api/alerts` | Scan listeners, update alert lifecycle, and return active alerts. |
| `GET /api/alert-history` | Return up to 100 active and resolved events. |
| `GET /docs` | Open FastAPI's interactive documentation. |

`GET /api/alerts` currently updates database state. Moving that work to a scheduled scan or an explicit mutation endpoint is a planned design improvement.

## Validation

Run from the repository root:

```bash
.venv/bin/python -m py_compile backend/main.py
cmake --build collector/build
./collector/build/network_collector
sudo systemctl is-active sentinellab
curl http://127.0.0.1:8000/api/status
curl http://127.0.0.1:8000/api/listening-ports
curl http://127.0.0.1:8000/api/alerts
curl http://127.0.0.1:8000/api/alert-history
```

Expected results:

- Python compilation succeeds silently.
- The collector prints valid JSON.
- The service reports `active`.
- All API requests return JSON.
- Active alerts are explainable.

## Security Model

- Uvicorn must remain bound to `127.0.0.1` unless authentication, TLS, authorization, firewall rules, and rate limits are deliberately designed first.
- The service runs as an unprivileged account, not root.
- `NoNewPrivileges=true`, `PrivateTmp=true`, and `UMask=0077` reduce service exposure.
- The data directory and SQLite database are restricted to the service account.
- Remote access uses an authenticated SSH tunnel.
- Packet payloads, credentials, messages, and DNS contents are not captured.
- Deployment-specific approved ports are not stored in Git.

A LAN-accessible listener is not automatically reachable from the public internet. Public reachability also depends on router forwarding, UPnP, firewall policy, reverse proxies, and tunnels.

## Git Safety

Do not commit:

- `.env` files or deployment overrides.
- Passwords, API keys, tokens, or private keys.
- Live hostnames, private addresses, or service inventories.
- `.venv/` or `__pycache__/`.
- `collector/build/`.
- SQLite databases or backups.
- Logs and temporary backup files.

Recommended ignore rules include:

```gitignore
.venv/
__pycache__/
*.pyc
collector/build/
*.db
*.db-*
*.db.*
*.sqlite
*.sqlite3
*.bak
*.backup
.env
.env.*
!.env.example
*.pem
*.key
id_rsa*
id_ed25519*
```

## Known Limitations

- Monitors one host, not the entire local network.
- Does not inspect packet payloads.
- Unprivileged inspection may not attribute every socket to a PID.
- Port approval does not verify the executable that owns the port.
- Alert fingerprints are based on port number.
- Browser traffic-rate history is not persisted.
- Multiple Uvicorn workers are not currently supported for alert scanning.
- The web application has no built-in authentication because it is designed for loopback-only access.

## Documentation

- `docs/SENTINELLAB_PROJECT_GUIDE.md` contains detailed installation, recovery, and troubleshooting guidance.
- `docs/SENTINELLAB_AI_HANDOFF.md` provides concise machine-oriented project context.

## License

No open-source license has been selected yet. Add an appropriate license before inviting others to reuse or redistribute the project.
