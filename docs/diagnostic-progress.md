# Live diagnostic progress

The dashboard uses Server-Sent Events (SSE) for the backend ping measurement and reports the other stages from the browser as their real requests start and finish. Progress is stage-based: the UI does not estimate elapsed work or display percentages.

## Browser behaviour

When a test starts, the progress panel lists these actual stages as they run:

- **Ping** — backend IPv4 ping measurement. The SSE stream reports its start and completion/failure.
- **DNS** — the backend DNS-check request.
- **Download + upload** — the Cloudflare browser speed test. The stage completes when that test returns its result.
- **IPv4/IPv6** — the backend protocol diagnostic.

Diagnostic profiles omit stages that are not part of the selected profile. A stage can be marked complete, partially complete, failed, or cancelled. The existing dashboard metrics, profile result renderer, history save, and final result messages remain the source of truth for measurements.

The **Cancel test** control closes the active SSE connection, aborts outstanding browser-to-backend fetches, and pauses the browser speed test. Completed measurements remain visible; active stages are marked cancelled.

## Backend SSE contract

The stream endpoint is:

~~~http
GET /api/network-quality/stream
GET /api/network-quality/stream?profile=quick
~~~

It uses `Content-Type: text/event-stream` and sends named events:

~~~text
event: progress
data: {"stage":"ping","status":"started","completed":[]}

event: progress
data: {"stage":"ping","status":"completed","completed":["ping"]}

event: result
data: {"target":"1.1.1.1","ping_ms":12.4,"packet_loss":0}

event: done
data: {"status":"completed"}
~~~

A failed ping sends `progress` with `status: "failed"`, a `failure` event with an HTTP-like status code and actionable detail, then `done` with `status: "failed"`. The `result` event uses the same result schema as `GET /api/network-quality`; profile requests use the existing `build_profile_result` shape.

Only stage transitions are emitted. Packet-level progress is not available from the current ping command, so no packet count, time estimate, or percentage is invented.

## Disconnect and cancellation

The server checks `Request.is_disconnected()` while the ping subprocess runs. When the client disconnects, the async task is cancelled and the child ping process is killed and reaped. The subprocess also has a bounded timeout: `max(30, packet_count * 2 + 10)` seconds.

The browser closes the EventSource on explicit cancellation. EventSource transport errors are handled by closing the stream and falling back to the existing JSON endpoint rather than replaying a new SSE diagnostic on automatic reconnect.

## Non-streaming fallback

If the browser has no `EventSource` support, or the SSE connection cannot be established/maintained, the frontend calls the existing `GET /api/network-quality` endpoint. The result still flows through the existing dashboard and profile renderers. The progress panel can show the ping stage as running/completed, but the fallback cannot provide live backend ping events.

The JSON endpoint remains available for older clients and integrations. Its synchronous subprocess call retains the existing hard timeout, so a fallback request is bounded even though the server cannot interrupt that synchronous call as promptly as the SSE path.

## Tests

- `tests/test_diagnostic_progress.py`: stream success/failure events, route content type/profile validation, disconnect cancellation, and child-process cleanup.
- `tests/diagnostic-progress.test.js`: stage-state rendering data, stream URL construction, EventSource event handling, and legacy JSON fallback.
