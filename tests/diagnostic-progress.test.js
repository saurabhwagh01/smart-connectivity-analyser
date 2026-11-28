const { test } = require("node:test");
const assert = require("node:assert/strict");

const {
    createDiagnosticProgressState,
    reduceDiagnosticProgress,
    formatDiagnosticProgress,
    buildNetworkQualityStreamUrl,
    buildNetworkQualityJsonUrl,
    requestNetworkQualityWithProgress
} = require("../js/script.js");

test("diagnostic progress reflects only actual stage statuses, never percentages", () => {
    let state = createDiagnosticProgressState();
    state = reduceDiagnosticProgress(state, { stage: "Ping", status: "started" });
    state = reduceDiagnosticProgress(state, { stage: "DNS", status: "completed" });
    state = reduceDiagnosticProgress(state, { stage: "Ping", status: "completed" });
    state = reduceDiagnosticProgress(state, { stage: "Download + upload", status: "partial" });

    const summary = formatDiagnosticProgress(state);
    assert.doesNotMatch(summary, /Running:/);
    assert.match(summary, /Completed: DNS, Ping/);
    assert.match(summary, /Partial: Download \+ upload/);
    assert.equal(summary.includes("%"), false);
});

test("invalid progress events leave the current state unchanged", () => {
    const state = createDiagnosticProgressState();
    assert.equal(
        reduceDiagnosticProgress(state, { stage: "Ping", status: "99%" }),
        state
    );
    assert.equal(
        reduceDiagnosticProgress(state, { stage: "", status: "started" }),
        state
    );
});

test("stream and legacy endpoint URLs preserve profile selection", () => {
    assert.equal(
        buildNetworkQualityStreamUrl("http://127.0.0.1:8000/api/", "quick check"),
        "http://127.0.0.1:8000/api/network-quality/stream?profile=quick+check"
    );
    assert.equal(
        buildNetworkQualityJsonUrl("http://127.0.0.1:8000/api/", "quick check"),
        "http://127.0.0.1:8000/api/network-quality?profile=quick%20check"
    );
    assert.equal(
        buildNetworkQualityStreamUrl("http://127.0.0.1:8000/api"),
        "http://127.0.0.1:8000/api/network-quality/stream"
    );
});

test("EventSource progress is consumed and the streamed result resolves", async () => {
    let instance;
    class FakeEventSource {
        constructor(url) {
            this.url = url;
            this.listeners = {};
            this.closed = false;
            instance = this;
        }
        addEventListener(name, handler) {
            this.listeners[name] = handler;
        }
        close() {
            this.closed = true;
        }
        emit(name, data) {
            this.listeners[name]?.({ data: JSON.stringify(data) });
        }
    }

    const updates = [];
    const resultPromise = requestNetworkQualityWithProgress("quick", {
        EventSourceImpl: FakeEventSource,
        fetchImpl: async () => {
            throw new Error("JSON fallback must not be used after a successful stream.");
        },
        onProgress: (...args) => updates.push(args)
    });

    assert.match(instance.url, /network-quality\/stream\?profile=quick$/);
    instance.emit("progress", { stage: "ping", status: "started", completed: [] });
    instance.emit("progress", { stage: "ping", status: "completed", completed: ["ping"] });
    const result = { ping_ms: 14.2, packet_loss: 0 };
    instance.emit("result", result);

    assert.deepEqual(await resultPromise, result);
    assert.equal(instance.closed, true);
    assert.deepEqual(updates.map((x) => x[1]), ["started", "completed"]);
});

test("server diagnostic failure rejects the stream without retrying the JSON endpoint", async () => {
    class FakeEventSource {
        constructor() {
            this.listeners = {};
            this.closed = false;
            queueMicrotask(() => this.listeners.failure?.({
                data: JSON.stringify({ status_code: 503, detail: "Ping unavailable." })
            }));
        }
        addEventListener(name, handler) { this.listeners[name] = handler; }
        close() { this.closed = true; }
    }

    let fallbackCalled = false;
    await assert.rejects(
        requestNetworkQualityWithProgress(null, {
            EventSourceImpl: FakeEventSource,
            fetchImpl: async () => {
                fallbackCalled = true;
                return { ok: true, json: async () => ({ ping_ms: 1 }) };
            }
        }),
        /Ping unavailable/
    );
    assert.equal(fallbackCalled, false);
});

test("EventSource transport failure falls back to the existing JSON endpoint", async () => {
    let instance;
    class FakeEventSource {
        constructor() {
            this.listeners = {};
            this.closed = false;
            instance = this;
        }
        addEventListener(name, handler) { this.listeners[name] = handler; }
        close() { this.closed = true; }
    }

    let requestedUrl;
    const result = await requestNetworkQualityWithProgress("stability", {
        EventSourceImpl: FakeEventSource,
        fetchImpl: async (url, options) => {
            requestedUrl = url;
            assert.equal(options.method, "GET");
            return { ok: true, json: async () => ({ ping_ms: 10, packet_loss: 0 }) };
        }
    });
    instance.onerror();

    assert.deepEqual(result, { ping_ms: 10, packet_loss: 0 });
    assert.equal(instance.closed, true);
    assert.equal(requestedUrl, "http://127.0.0.1:8000/api/network-quality?profile=stability");
});

test("browsers without EventSource use the legacy JSON result flow", async () => {
    let requestedUrl;
    const result = await requestNetworkQualityWithProgress("quick", {
        EventSourceImpl: null,
        fetchImpl: async (url) => {
            requestedUrl = url;
            return { ok: true, json: async () => ({ ping_ms: 8 }) };
        }
    });

    assert.deepEqual(result, { ping_ms: 8 });
    assert.equal(requestedUrl, "http://127.0.0.1:8000/api/network-quality?profile=quick");
});
