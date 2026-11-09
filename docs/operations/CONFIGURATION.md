# Configuration and Runtime Operations

## Example config
```json
{
  "server": {"host": "127.0.0.1", "port": 8090},
  "collector": {"poll_interval_ms": 1000, "request_timeout_ms": 500, "max_response_bytes": 1048576, "max_processes": 3},
  "history": {"enabled": true, "directory": "./data", "retention_days": 7},
  "endpoints": [
    {"id": "local-8080", "url": "http://127.0.0.1:8080", "enabled": true, "engine": "auto"},
    {"id": "local-8081", "url": "http://127.0.0.1:8081", "enabled": false, "engine": "auto"},
    {"id": "local-8082", "url": "http://127.0.0.1:8082", "enabled": false, "engine": "auto"}
  ]
}
```

## Rules
- Maximum three enabled endpoints in MVP.
- Endpoint IDs are unique and stable.
- HTTP/HTTPS accepted; local use defaults to loopback.
- Initial engine values: auto, polystrata, llamacpp, exl3rdna4.
- Manual engine value is an override, not an auto-detection result.
- Poll interval is positive and bounded; 1000 ms is initial proposal.
- Request timeout is shorter than cycle budget.
- Seven-day history retention is a proposed default.
- Store telemetry outside source-controlled fixtures.

## Endpoint tracking from the dashboard
- Users enter a loopback local port on the dashboard; the companion adds `http://127.0.0.1:<port>` (engine auto) and starts tracking it on the next collector cycle.
- Each endpoint card exposes Pause (disable, keep in config) and Remove (delete from config).
- Every change is written back to the config file in place; on restart, `load_config` re-validates it (same three-enabled cap, loopback-only URLs).
- If a write fails, the in-memory change still works and the error is surfaced via `config_error` in `/api/config`.

## Lifecycle
Start one collector loop and one HTTP server. Browser tabs are clients only. On graceful shutdown flush history and stop collector. On startup recover valid JSONL lines and report malformed trailing records without discarding earlier data.

## Diagnostics
Expose last probe, selected adapter, detection signals, last success and last error. Never log prompts, completions, credentials or arbitrary full response payloads.