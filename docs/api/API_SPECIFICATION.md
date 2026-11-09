# Local HTTP API Specification

**Base:** http://127.0.0.1:8090  
**Version:** Proposed API v1

## Principle
Serve the latest cached collector snapshot. Browser/API reads must not trigger fresh inference-server polling.

## Routes
| Method | Route | Purpose |
|---|---|---|
| GET | /api/health | Companion liveness and collector state |
| GET | /api/endpoints | Configured targets and detection state |
| GET | /api/snapshot | Latest host sample and endpoint observations |
| GET | /api/history?from=&to=&endpoint_id=&session_id=&limit= | Bounded historical query |
| GET | /api/config | Safe effective configuration with secrets redacted (includes `config_error` when a config write failed) |
| GET | / | Static dashboard |
| POST | /api/endports | Start tracking a loopback local port; body `{"port":1-65535}` → 201 `{"endpoint":…}` |
| PATCH | /api/endpoints/{id} | Pause/resume; body `{"enabled":true\|false}` → 200 `{"endpoint":…}` |
| DELETE | /api/endpoints/{id} | Stop tracking and remove from config → 200 `{"ok":true}` |

Configuration mutation is limited to endpoint tracking (loopback ports only) and is persisted to the config file, re-validated on next start.

## Example health
```json
{"status":"ok","api_version":"1","collector":{"running":true,"last_cycle_at":"2026-11-08T06:30:00Z"}}
```

## Error shape
```json
{"error":{"code":"INVALID_QUERY","message":"The requested time range is invalid."}}
```

## Semantics
- HTTP 200 may include endpoint state unavailable; the API request itself succeeded.
- HTTP 400 invalid query/config input (or `ENDPOINT_LIMIT` when more than three endpoints would be enabled).
- HTTP 404 unknown resource.
- HTTP 409 `CONFLICT` for a duplicate endpoint/port.
- HTTP 500 unexpected companion failure.
- Missing metrics are null with availability reason.

## Constraints
Loopback-only by default, no wildcard CORS, bounded response/history sizes, no arbitrary URL proxy, and no API handler that waits on live engine calls.