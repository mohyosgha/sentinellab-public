# SentinelLab Project Guide (Public Edition)

This document is the public-safe maintenance, recovery, development, and operating guide for SentinelLab. It is intended for project owners and future maintainers.

All values in angle brackets, such as `<server-user>`, are placeholders. Keep real hostnames, usernames, private addresses, credentials, and environment-specific service inventories in private operator notes outside Git.

For a shorter machine-oriented handoff, also read `SENTINELLAB_AI_HANDOFF.md`.

## 1. Project Summary

SentinelLab is a defensive network-security dashboard designed to run on a self-hosted Ubuntu Linux machine.

It combines:

- C++17 for low-level Linux network-interface counters.
- Python and FastAPI for APIs, security analysis, and orchestration.
- JavaScript, HTML, and CSS for the browser dashboard.
- SQLite for persistent security-alert history.
- systemd for automatic background operation.
- SSH port forwarding for private access without exposing the dashboard directly to the LAN or internet.

The current FastAPI application version is `0.4.0`.

The application monitors the Ubuntu server itself. It does not automatically observe traffic exchanged exclusively between other devices on the home network.

## 2. Current Capabilities

SentinelLab currently provides:

- Total bytes received and sent across non-loopback Linux interfaces.
- Live download and upload rates calculated in the browser.
- A count of visible established TCP connections.
- A list of visible TCP listening sockets.
- Local-only versus LAN-accessible listener classification.
- An approved LAN-port list.
- Detection of unexpected LAN-accessible TCP ports.
- SQLite persistence for detected-port alerts.
- Active and resolved alert states.
- Automatic startup after server reboots.
- Interactive FastAPI documentation.
- Private browser access through an SSH tunnel.

## 3. Architecture

```text
Ubuntu Linux kernel
    |
    | /proc/net/dev
    v
C++ network_collector
    |
    | JSON on stdout
    v
Python FastAPI backend
    |        |             |
    |        |             +--> psutil connection/listener inspection
    |        +----------------> SQLite alert history
    |
    | JSON APIs
    v
JavaScript dashboard
    |
    | served only on 127.0.0.1:8000
    v
SSH tunnel to the user's browser
```

### Data flow

1. The browser requests `/api/status` every five seconds.
2. Python launches the compiled C++ collector.
3. C++ reads `/proc/net/dev`, ignores loopback, and prints JSON.
4. Python combines that output with connection information from `psutil`.
5. The browser compares consecutive byte totals to calculate bytes per second.
6. The browser also requests listening ports, active alerts, and alert history.
7. Python detects unexpected LAN listeners and records their lifecycle in SQLite.

## 4. Deployment Template

Record actual deployment values privately. The public repository should use this template:

```text
Server hostname: <server-hostname>
Server operating system: <supported-ubuntu-release>
Server address or private DNS name: <server-address>
Service account: <server-user>
Project directory: /home/<server-user>/sentinellab
Dashboard bind address: 127.0.0.1
Dashboard port: 8000
systemd service: sentinellab.service
```

The server address may change unless it is reserved or provided through private DNS. The application does not require this address to be hardcoded; the client-side SSH command must use the operator's current private address or hostname.

## 5. Repository Layout

```text
sentinellab/
├── .git/
├── .gitignore
├── .venv/                         # Ignored by Git
├── README.md
├── requirements.txt
├── backend/
│   └── main.py
├── collector/
│   ├── CMakeLists.txt
│   ├── main.cpp
│   └── build/                     # Ignored by Git
│       └── network_collector
├── data/
│   └── sentinellab.db             # Ignored by Git
├── frontend/
│   └── index.html
└── tests/                         # Reserved for future automated tests
```

Backups ending in `.bak` are ignored by Git.

## 6. File Responsibilities

### `collector/main.cpp`

The C++ collector:

- Opens `/proc/net/dev`.
- Skips the two header lines.
- Parses the 16 interface counters on each remaining line.
- Ignores interface `lo`.
- Sums receive bytes and transmit bytes across all other interfaces.
- Prints one JSON object to standard output.

Expected output:

```json
{"bytes_received":123456,"bytes_sent":654321,"source":"cpp"}
```

The program does not capture packet contents, credentials, messages, DNS queries, or payloads.

### `collector/CMakeLists.txt`

Defines the C++17 executable named `network_collector`.

Build commands:

```bash
cmake -S collector -B collector/build
cmake --build collector/build
```

### `backend/main.py`

The Python backend:

- Serves the dashboard.
- Runs the C++ collector with a two-second timeout.
- Parses collector JSON.
- Uses `psutil` for connection and listener inspection.
- Loads and validates the deployment-local approved-port rule from the `SENTINELLAB_APPROVED_LAN_PORTS` environment variable.
- Detects unexpected LAN-accessible listeners.
- Initializes and updates the SQLite database.
- Exposes the API endpoints.

### `frontend/index.html`

The frontend is a self-contained HTML document containing:

- Page structure.
- CSS styling.
- JavaScript API calls.
- Live-rate calculations.
- Listening-port rendering.
- Active-alert rendering.
- Alert-history rendering.

It uses no external JavaScript framework and no CDN dependency.

### `data/sentinellab.db`

SQLite database containing alert history. It is generated automatically and intentionally excluded from Git.

Do not delete this file if historical alerts need to be preserved.

### `/etc/systemd/system/sentinellab.service`

This deployment file exists outside the Git repository.

Expected contents:

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
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Replace the angle-bracket placeholders before installing the service. The deployed service intentionally omits `--reload`.

## 7. API Contract

### `GET /`

Returns `frontend/index.html`.

### `GET /api/status`

Returns current server status.

Example:

```json
{
  "hostname": "sentinellab-host",
  "bytes_received": 123456,
  "bytes_sent": 654321,
  "active_connections": 3,
  "network_source": "cpp"
}
```

Notes:

- Byte values are cumulative totals, normally since boot or interface initialization.
- `active_connections` counts visible TCP sockets in the `ESTABLISHED` state.
- It is not a count of people or devices.
- Unprivileged `psutil` inspection can omit protected connections.

### `GET /api/listening-ports`

Returns visible TCP listening sockets.

Example:

```json
{
  "count": 2,
  "ports": [
    {
      "address": "0.0.0.0",
      "port": 22,
      "pid": null
    },
    {
      "address": "127.0.0.1",
      "port": 8000,
      "pid": 12345
    }
  ]
}
```

`pid: null` is expected when the unprivileged service cannot retrieve process ownership. Do not run the dashboard as root merely to populate these values.

### `GET /api/alerts`

Scans current listeners, records alert state in SQLite, and returns active alerts.

Example unexpected listener:

```json
{
  "count": 1,
  "alerts": [
    {
      "id": "unexpected-port-9999",
      "severity": "warning",
      "title": "Unexpected LAN-exposed port",
      "description": "TCP port 9999 is listening on 0.0.0.0 and is not approved.",
      "port": 9999,
      "address": "0.0.0.0"
    }
  ]
}
```

Important: calling this endpoint performs the database lifecycle update. Alerts not found in that scan are marked inactive.

This state-changing behavior is a known design debt because HTTP `GET` should normally be read-only. Move scanning and persistence to a scheduled task or an explicit mutation endpoint before exposing the API beyond its loopback-only design.

### `GET /api/alert-history`

Returns up to 100 events ordered with active alerts first and then by most recent observation.

Example:

```json
{
  "count": 1,
  "events": [
    {
      "id": "unexpected-port-9999",
      "severity": "warning",
      "title": "Unexpected LAN-exposed port",
      "description": "TCP port 9999 is listening on 0.0.0.0 and is not approved.",
      "port": 9999,
      "address": "0.0.0.0",
      "first_seen": "2025-01-01T12:00:00+00:00",
      "last_seen": "2025-01-01T12:05:00+00:00",
      "active": false
    }
  ]
}
```

### `GET /docs`

FastAPI Swagger interface for manually exercising the API.

## 8. Alert Detection Logic

Approved LAN ports are loaded at startup from the optional `SENTINELLAB_APPROVED_LAN_PORTS` environment variable. The public default is empty. Its format is a comma-separated list of `PORT=LABEL` entries:

```text
22=SSH,8443=Example service
```

Supply real values through a private systemd drop-in or other deployment-local environment configuration. Do not commit the live service inventory. Operators must approve only services they have deliberately enabled and independently verified.

Current behavior:

1. Gather visible TCP listeners.
2. Ignore loopback addresses beginning with `127.` and IPv6 `::1`.
3. Deduplicate IPv4 and IPv6 listeners by port number.
4. Ignore ports in `APPROVED_LAN_PORTS`.
5. Create a warning for every other LAN-accessible port.

The fingerprint is currently based on the port:

```text
unexpected-port-<port>
```

Consequences:

- IPv4 and IPv6 listeners on the same port become one alert.
- A later service using the same port updates the existing history row.
- The system detects unexpected exposure, not malware intent.

An alert means “review this port.” It does not prove compromise.

## 9. SQLite Schema and Lifecycle

Table: `alert_history`

```sql
CREATE TABLE alert_history (
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
);
```

Lifecycle:

- New fingerprint: insert with `first_seen`, `last_seen`, and `active = 1`.
- Existing fingerprint seen again: retain `first_seen`, update `last_seen`, and set `active = 1`.
- Previously recorded fingerprint absent from the newest scan: set `active = 0`.

Timestamps are stored as ISO 8601 UTC strings.

The dashboard converts them to the browser's local time for display.

## 10. Browser Rate Calculation

The C++ collector returns totals, not instantaneous rates.

JavaScript calculates speed using consecutive samples:

```text
rate = (new byte total - previous byte total) / elapsed seconds
```

The first sample displays `Calculating…` because there is no earlier value.

Negative differences are clamped to zero. This handles interface counter resets or server reboots.

The frontend polling interval is currently 5000 milliseconds.

## 11. Security Model

### Intended protections

- Uvicorn binds only to `127.0.0.1:8000`.
- Remote browser access uses an encrypted SSH tunnel.
- The application runs as a dedicated unprivileged account, not root.
- systemd applies `NoNewPrivileges=true`.
- Packet payloads are not captured.
- Secrets and the SQLite database are excluded from Git.

### What “LAN exposed” means

Addresses such as `0.0.0.0`, `::`, or the server's LAN address accept connections through a network interface.

This does not automatically mean the service is reachable from the public internet. Internet exposure depends on:

- Router port forwarding.
- UPnP mappings.
- DMZ configuration.
- Firewall rules.
- Reverse proxies or tunnels.

### Environment-specific services

Do not publish a live inventory of private services merely to document this project. Each operator should privately record and periodically verify approved listeners. Typical examples may include SSH on TCP 22 and SentinelLab on TCP 8000 bound to loopback. Loopback DNS or container-runtime listeners can also appear, but process ownership must be verified on the actual host.

### Important rule

Never change Uvicorn to `--host 0.0.0.0` without a deliberate authentication, TLS, firewall, and authorization design.

## 12. Daily Operation

### Open the dashboard

On the client computer, open PowerShell and run:

```powershell
ssh -L 8000:127.0.0.1:8000 <server-user>@<server-address>
```

Leave that session open, then browse to:

```text
http://localhost:8000
```

Other useful URLs:

```text
http://localhost:8000/docs
http://localhost:8000/api/status
http://localhost:8000/api/listening-ports
http://localhost:8000/api/alerts
http://localhost:8000/api/alert-history
```

### Check service health

```bash
sudo systemctl status sentinellab --no-pager
sudo systemctl is-active sentinellab
curl http://127.0.0.1:8000/api/status
```

### Restart after Python changes

```bash
sudo systemctl restart sentinellab
sudo systemctl status sentinellab --no-pager
```

Frontend-only changes generally require only a hard browser refresh:

```text
Ctrl+F5
```

### View logs

```bash
sudo journalctl -u sentinellab -n 100 --no-pager
sudo journalctl -u sentinellab -f
```

Exit follow mode with `Ctrl+C`.

## 13. Installation or Full Rebuild

### System prerequisites

```bash
sudo apt update
sudo apt install -y build-essential cmake python3-venv git
```

### Python environment

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### C++ build

```bash
cmake -S collector -B collector/build
cmake --build collector/build
./collector/build/network_collector
```

### Manual development run

Stop the system service first so port 8000 is available:

```bash
sudo systemctl stop sentinellab
source .venv/bin/activate
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

When development is complete:

```bash
sudo systemctl start sentinellab
```

Do not run the manual server and systemd service on port 8000 simultaneously.

## 14. Safe Functional Test

Warning: this test intentionally opens an unauthenticated listener on all network interfaces. Run it only on a trusted or isolated LAN with suitable host-firewall rules, use an empty directory, and stop it immediately after verifying the alert. Prefer automated mocked tests when they become available.

Create an empty directory and a temporary LAN listener:

```bash
mkdir -p ~/sentinellab/test-listener
python3 -m http.server 9999 --bind 0.0.0.0 --directory ~/sentinellab/test-listener
```

In another SSH session:

```bash
curl http://127.0.0.1:8000/api/alerts
curl http://127.0.0.1:8000/api/alert-history
```

Expected behavior while the listener is active:

- `/api/alerts` includes `unexpected-port-9999`.
- History contains port 9999 with `active: true`.

Stop the temporary server with `Ctrl+C`, then scan again:

```bash
curl http://127.0.0.1:8000/api/alerts
curl http://127.0.0.1:8000/api/alert-history
```

Expected behavior afterward:

- Active-alert count returns to zero.
- History retains port 9999 with `active: false`.

Remove the empty directory:

```bash
rmdir ~/sentinellab/test-listener
```

## 15. Troubleshooting

### Browser says “Unable to connect”

Check the service on the server:

```bash
sudo systemctl is-active sentinellab
curl http://127.0.0.1:8000/api/status
```

If the server curl works, recreate the SSH tunnel from a local PowerShell prompt:

```powershell
ssh -L 8000:127.0.0.1:8000 <server-user>@<server-address>
```

The tunnel command must originate on the client computer, not from an already-open shell on the server.

### SSH says “channel open failed: Connection refused”

The tunnel exists, but nothing is listening on server port 8000.

```bash
sudo systemctl restart sentinellab
sudo journalctl -u sentinellab -n 100 --no-pager
```

### Uvicorn reports `[Errno 98] address already in use`

A manual Uvicorn instance and systemd are competing for port 8000.

Find the listener:

```bash
sudo ss -ltnp 'sport = :8000'
```

Stop the manual instance with `Ctrl+C`, then restart the service:

```bash
sudo systemctl restart sentinellab
```

### Backend syntax error

View the exact line:

```bash
sudo journalctl -u sentinellab -n 100 --no-pager
python -m py_compile backend/main.py
```

If a known-good backup exists:

```bash
cp backend/main.py.bak backend/main.py
sudo systemctl restart sentinellab
```

Or restore the committed version carefully:

```bash
git diff -- backend/main.py
git show HEAD:backend/main.py
```

Do not discard uncommitted work without reviewing it first.

### `/api/status` returns 503

Test the collector directly:

```bash
./collector/build/network_collector
```

If missing, rebuild:

```bash
cmake -S collector -B collector/build
cmake --build collector/build
sudo systemctl restart sentinellab
```

### `network_source` is not `cpp`

Confirm that `backend/main.py` points to:

```text
/home/<server-user>/sentinellab/collector/build/network_collector
```

Run that binary manually and verify valid JSON.

### Database errors

Inspect ownership and permissions:

```bash
ls -ld ~/sentinellab/data
ls -l ~/sentinellab/data/sentinellab.db
```

They should be writable by the configured unprivileged service account.

Check the service log for the exact SQLite error.

Before any repair, back up the database outside the Git repository:

```bash
install -d -m 700 ~/sentinellab-private-backups
cp ~/sentinellab/data/sentinellab.db ~/sentinellab-private-backups/sentinellab.db.backup
```

### PIDs show as `null` or “Hidden”

This is expected for connections whose process information requires elevated privileges. It is preferable to retain least privilege rather than run the dashboard as root.

### Connection count seems too high

The number counts TCP sockets, not users or devices. SSH, browser polling, Docker services, and one application opening multiple sockets can all increase it.

### Download or upload rate shows zero

The server may simply be idle. Generate legitimate traffic or wait for another polling cycle. The first poll cannot calculate a rate.

### HTML changes do not appear

Use `Ctrl+F5` to bypass browser cache. Confirm the edited file is:

```text
/home/<server-user>/sentinellab/frontend/index.html
```

## 16. Git Workflow

Current branch: `main`.

Before editing:

```bash
cd ~/sentinellab
git status
```

After editing and testing:

```bash
git diff
git add <specific-files>
git diff --cached
git commit -m "Describe the change"
```

Never commit:

- `.env` files.
- Passwords or API keys.
- SSH keys.
- Credentials or workflow exports from unrelated services.
- `.venv/`.
- `collector/build/`.
- SQLite database files.
- Temporary backups.

Expected `.gitignore`:

```gitignore
.venv/
__pycache__/
*.pyc
collector/build/
*.db
*.bak
*.backup
*.db-*
*.db.*
*.sqlite
*.sqlite3
.env
.env.*
!.env.example
*.pem
*.key
id_rsa*
id_ed25519*
```

## 17. Backups and Recovery

### Source recovery

Source code is preserved by local Git commits.

```bash
git status
git log --oneline --decorate -n 10
```

Inspect a committed file without modifying the working tree:

```bash
git show HEAD:backend/main.py
```

### Alert-history backup

SQLite history is not in Git. Back it up outside the repository:

```bash
install -d -m 700 ~/sentinellab-private-backups
cp ~/sentinellab/data/sentinellab.db ~/sentinellab-private-backups/sentinellab-$(date +%Y%m%d).db.backup
```

### systemd backup

The service definition is outside the repository:

```bash
sudo cp /etc/systemd/system/sentinellab.service /etc/systemd/system/sentinellab.service.backup
```

## 18. How to Extend the Project Safely

### Approve another LAN service

Only after identifying and intentionally accepting the service, update the private environment value. With systemd, use a service drop-in:

```bash
sudo systemctl edit sentinellab
```

Example drop-in:

```ini
[Service]
Environment="SENTINELLAB_APPROVED_LAN_PORTS=22=SSH,12345=Example service"
```

This replaces the complete value, so retain every still-approved entry. Then reload, restart, and test:

```bash
python -m py_compile backend/main.py
sudo systemctl daemon-reload
sudo systemctl restart sentinellab
curl http://127.0.0.1:8000/api/alerts
```

Do not approve a port merely to silence an unexplained alert.

### Add another API endpoint

1. Put data-collection logic in a helper function.
2. Keep the route function small.
3. Return JSON-serializable values.
4. Avoid blocking calls without timeouts.
5. Preserve existing response field names unless the frontend is updated simultaneously.
6. Restart systemd and test through both curl and `/docs`.

### Change the C++ collector

1. Modify `collector/main.cpp`.
2. Build it.
3. Run it manually.
4. Confirm it prints exactly one valid JSON object.
5. Confirm `/api/status` still reports `network_source: cpp`.

### Add full-network visibility

The current server is an ordinary Ethernet-connected host. A switched network does not send all other devices' unicast traffic to it.

Network-wide visibility requires one of:

- Router API or SNMP telemetry.
- A managed-switch mirror port.
- Running the monitor on the gateway.
- Agents installed on other devices.

Do not enable promiscuous capture and assume it provides complete visibility on a switched network.

### Add authentication

Current protection is loopback binding plus SSH authentication. If the dashboard is ever exposed beyond loopback, add authentication, TLS, authorization, CSRF consideration, rate limits, and firewall restrictions before changing the bind address.

## 19. Known Limitations

- Monitors the server, not the full home network.
- Does not inspect packet payloads.
- Does not attribute all sockets to processes without additional privilege.
- Port-based approval does not validate which executable owns the port.
- The frontend keeps rate history only in browser memory.
- Traffic totals reset when underlying kernel counters reset.
- SQLite tracks alert fingerprints by port, not by process identity.
- No automated test suite is implemented yet.
- No authentication exists inside the web application because it is designed for loopback-only access.
- Router port forwarding and UPnP are outside the application's visibility.

## 20. Recommended Future Enhancements

Prioritized suggestions:

1. Add automated unit tests for alert classification and database lifecycle.
2. Move approved services into a validated configuration file.
3. Add process-name attribution through a narrowly scoped helper rather than running the web service as root.
4. Add traffic-sample persistence and a chart.
5. Add an alert acknowledgment field.
6. Add alert retention and database-pruning policies.
7. Add structured logging.
8. Add a health endpoint for service monitoring.
9. Package the systemd file inside the repository under `deploy/`.
10. Add CI that builds C++, checks Python syntax, and validates frontend files.
11. Make `GET /api/alerts` read-only by moving lifecycle updates to a scheduled scan or explicit mutation endpoint.
12. Make hostname and PID reporting optional to reduce information disclosure if the access model changes.

## 21. Final Validation Checklist

Run from the repository root (normally `/home/<server-user>/sentinellab`):

```bash
git status
python -m py_compile backend/main.py
./collector/build/network_collector
sudo systemctl is-active sentinellab
curl http://127.0.0.1:8000/api/status
curl http://127.0.0.1:8000/api/listening-ports
curl http://127.0.0.1:8000/api/alerts
curl http://127.0.0.1:8000/api/alert-history
```

Expected results:

- Git is clean before release.
- Python compilation succeeds silently.
- C++ prints valid JSON.
- Service state is `active`.
- All API calls return JSON.
- `/api/status` reports `network_source: cpp`.
- Active alerts are explainable.
- Dashboard loads through the SSH tunnel.

## 22. Glossary

- **Bind address:** Network address on which a server accepts connections.
- **Loopback:** Local-only networking, normally `127.0.0.0/8` or `::1`.
- **LAN exposed:** Reachable through a server network interface; not necessarily public-internet exposed.
- **Listening socket:** A socket waiting to accept inbound connections.
- **Established connection:** An active TCP session between endpoints.
- **Port forward:** Router rule sending inbound internet traffic to a device on the LAN.
- **UPnP mapping:** Port mapping created dynamically by an application or device.
- **Fingerprint:** Stable identifier used to update an existing alert-history row.
- **Resolved alert:** Previously observed condition that is no longer present.
- **systemd:** Ubuntu service manager used to run SentinelLab automatically.
