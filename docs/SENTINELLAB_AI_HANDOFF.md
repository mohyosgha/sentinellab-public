# SentinelLab AI Handoff (Public Edition)

Use this file as the first context document when asking an AI system to maintain or extend SentinelLab.

All angle-bracket values are deployment placeholders. Do not place real usernames, hostnames, private addresses, credentials, or unrelated service inventories in the public repository.

## Objective

Maintain a defensive, least-privilege network-security dashboard on a self-hosted Ubuntu Linux machine. Preserve private SSH-tunnel access and avoid expanding network exposure without explicit human approval.

## Deployment Template

```text
Host: <server-hostname>
OS: <supported-ubuntu-release>
User: <server-user>
Repository: /home/<server-user>/sentinellab
Service: sentinellab.service
Bind: 127.0.0.1:8000
FastAPI version label: 0.4.0
Database: /home/<server-user>/sentinellab/data/sentinellab.db
```

The client normally connects with:

```powershell
ssh -L 8000:127.0.0.1:8000 <server-user>@<server-address>
```

The server IP may change. Do not hardcode it into application code.

## Architecture in One Paragraph

`collector/main.cpp` reads cumulative byte counters from `/proc/net/dev`, excludes `lo`, sums all other interfaces, and emits JSON. `backend/main.py` launches that binary, uses unprivileged `psutil` to inspect TCP connections and listeners, loads the deployment-local approved-port list from `SENTINELLAB_APPROVED_LAN_PORTS`, and persists alert lifecycle in SQLite. `frontend/index.html` polls four APIs every five seconds, derives upload/download rates from counter deltas, and renders status, active alerts, history, and listeners. systemd runs Uvicorn as a dedicated unprivileged account, bound to loopback only.

## Repository Map

```text
backend/main.py             FastAPI, detection, SQLite
collector/main.cpp          Linux byte-counter collector
collector/CMakeLists.txt    C++17 build
frontend/index.html         HTML/CSS/JavaScript dashboard
data/sentinellab.db         Runtime alert history; not in Git
requirements.txt            Python environment
README.md                   User-facing overview
```

## API Contracts That Must Remain Stable

### `/api/status`

```json
{
  "hostname": "string",
  "bytes_received": 0,
  "bytes_sent": 0,
  "active_connections": 0,
  "network_source": "cpp"
}
```

### `/api/listening-ports`

```json
{
  "count": 0,
  "ports": [
    {"address": "string", "port": 0, "pid": null}
  ]
}
```

### `/api/alerts`

```json
{
  "count": 0,
  "alerts": [
    {
      "id": "unexpected-port-9999",
      "severity": "warning",
      "title": "Unexpected LAN-exposed port",
      "description": "string",
      "port": 9999,
      "address": "0.0.0.0"
    }
  ]
}
```

Calling this endpoint also records current alert state and marks unseen historical alerts inactive.

### `/api/alert-history`

```json
{
  "count": 0,
  "events": [
    {
      "id": "string",
      "severity": "warning",
      "title": "string",
      "description": "string",
      "port": 9999,
      "address": "0.0.0.0",
      "first_seen": "ISO-8601 UTC",
      "last_seen": "ISO-8601 UTC",
      "active": false
    }
  ]
}
```

## Approved-Service Configuration

The optional `SENTINELLAB_APPROVED_LAN_PORTS` environment variable uses comma-separated `PORT=LABEL` entries. Its public default is empty. Supply real values only through private deployment configuration, such as a systemd drop-in:

```ini
[Service]
Environment="SENTINELLAB_APPROVED_LAN_PORTS=22=SSH,8443=Example service"
```

Do not add a port merely to silence an alert. Identify the owning service and obtain human confirmation first. Never commit the live service inventory.

## Non-Negotiable Safety Invariants

1. Keep Uvicorn bound to `127.0.0.1` unless the human explicitly approves a complete exposure/authentication design.
2. Do not run the FastAPI or systemd service as root.
3. Do not remove `NoNewPrivileges=true` without a documented reason.
4. Do not commit `.env`, SQLite databases, private keys, credentials, `.venv`, or compiled build output.
5. Do not delete or recreate the SQLite database during routine fixes.
6. Do not interpret an unexpected port as proof of compromise; report it as a condition requiring investigation.
7. Preserve existing JSON field names or update the frontend in the same change.
8. Preserve the C++ collector's one-object JSON stdout contract.
9. Add timeouts to external processes and network operations.
10. Treat router forwarding, UPnP, and internet exposure as separate from local listener detection.

## Important Behavioral Details

- The C++ values are cumulative, not instantaneous.
- JavaScript calculates rates from consecutive five-second samples.
- The first frontend sample cannot produce a rate.
- `active_connections` counts visible established TCP sockets, not devices.
- `pid` may be null because the service is intentionally unprivileged.
- Loopback means `127.*` or `::1`.
- Alert deduplication is currently by port only.
- `/api/alerts` currently performs persistence updates; `/api/alert-history` is read-only. Treat the state-changing `GET` behavior as design debt and move it to a scheduled task or explicit mutation endpoint before broadening access.
- The database returns at most 100 history rows.
- The application monitors the host, not all LAN traffic.

## Environment Verification

- TCP 8000 should remain bound to loopback for SentinelLab.
- TCP 22 may be approved when SSH is intentionally enabled.
- DNS and container-runtime listeners can vary between deployments.
- Router forwarding, VPN overlays, reverse tunnels, and firewall policy are outside this application's visibility.

Keep the real listener inventory and remote-access details in private operator notes. Re-verify process ownership and current configuration before approving any service.

## Required Validation After Changes

```bash
cd /home/<server-user>/sentinellab
python -m py_compile backend/main.py
cmake --build collector/build
./collector/build/network_collector
sudo systemctl restart sentinellab
sudo systemctl is-active sentinellab
curl http://127.0.0.1:8000/api/status
curl http://127.0.0.1:8000/api/listening-ports
curl http://127.0.0.1:8000/api/alerts
curl http://127.0.0.1:8000/api/alert-history
```

Check logs on failure:

```bash
sudo journalctl -u sentinellab -n 100 --no-pager
```

After frontend-only changes, use `Ctrl+F5` in the browser.

## Safe Alert Regression Test

Warning: this test intentionally exposes an unauthenticated temporary listener on all interfaces. Use it only on a trusted or isolated LAN with suitable firewall rules, serve only an empty directory, and stop it immediately after validation. Prefer a mocked automated regression test when available.

```bash
mkdir -p ~/sentinellab/test-listener
python3 -m http.server 9999 --bind 0.0.0.0 --directory ~/sentinellab/test-listener
```

While active, `/api/alerts` must contain port 9999 and history must show `active: true`. After `Ctrl+C` and another `/api/alerts` call, history must retain the event with `active: false`.

## Troubleshooting Decision Tree

### Browser unavailable

1. `curl http://127.0.0.1:8000/api/status` on the server.
2. If curl fails, inspect `systemctl` and `journalctl`.
3. If curl works, recreate the SSH tunnel from the client computer.

### Address already in use

1. `sudo ss -ltnp 'sport = :8000'`.
2. Stop a manual Uvicorn process.
3. Restart `sentinellab.service`.

### Collector failure

1. Run `./collector/build/network_collector`.
2. Validate one JSON object on stdout.
3. Rebuild with CMake if needed.
4. Restart the systemd service.

### Python failure

1. Run `python -m py_compile backend/main.py`.
2. Read the exact traceback from systemd logs.
3. Inspect Git diff and restore only after preserving intended work.

### SQLite failure

1. Back up `data/sentinellab.db`.
2. Inspect directory ownership and disk space.
3. Do not delete the database as a first response.

## Expected Git Hygiene

Use the `main` branch unless the repository documents another workflow. Run `git status` before and after changes, inspect diffs before staging, and do not publish deployment-specific notes.

Expected ignore rules:

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

## Good Next Enhancements

Prefer this order:

1. Unit tests for `is_loopback_address`, `detect_alerts`, and SQLite lifecycle.
2. Add tests for the validated `SENTINELLAB_APPROVED_LAN_PORTS` parser and document deployment-local configuration.
3. Add a health endpoint.
4. Add structured logging.
5. Persist traffic samples and render a chart.
6. Package deployment files under `deploy/`.
7. Add CI for Python syntax, C++ build, and tests.
8. Add narrow process attribution without elevating the web service.
9. Make alert reads side-effect free by moving persistence updates out of `GET /api/alerts`.
10. Make hostname and PID fields optional if the access model ever expands beyond loopback.

For full-network monitoring, design a new collector around router telemetry, a gateway, port mirroring, or agents. Do not claim host-local counters provide whole-network visibility.

## Source of Truth

When this handoff conflicts with the running code, inspect:

1. Git history and current working tree.
2. `backend/main.py` and API behavior.
3. `collector/main.cpp` output.
4. `/etc/systemd/system/sentinellab.service`.
5. systemd logs.

Update this handoff whenever architecture, endpoint schemas, security boundaries, deployment paths, or approved services change.
