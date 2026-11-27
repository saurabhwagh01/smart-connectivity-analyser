const test = require("node:test");
const assert = require("node:assert/strict");
const {
    formatProtocolSummary,
    runNetworkProtocolTest
} = require("../js/script.js");

test("formats dual-stack connectivity", () => {
    assert.equal(
        formatProtocolSummary({
            ipv4: { status: "available" },
            ipv6: { status: "available" }
        }),
        "Server: IPv4 connected · IPv6 connected"
    );
});

test("keeps IPv4-only connectivity clear when IPv6 times out", () => {
    assert.equal(
        formatProtocolSummary({
            connected: true,
            ipv4: { status: "available" },
            ipv6: { status: "unavailable", reason: "timeout" }
        }),
        "Server: IPv4 connected · IPv6 connection timed out"
    );
});

test("reports unsupported IPv6 separately", () => {
    assert.equal(
        formatProtocolSummary({
            connected: true,
            ipv4: { status: "available" },
            ipv6: { status: "unsupported", reason: "not_supported" }
        }),
        "Server: IPv4 connected · IPv6 unsupported"
    );
});

test("distinguishes DNS failures and missing diagnostic data", () => {
    assert.equal(
        formatProtocolSummary({
            ipv4: { status: "unavailable", reason: "dns_failure" },
            ipv6: { status: "unavailable", reason: "connection_failure" }
        }),
        "Server: IPv4 DNS lookup failed · IPv6 connection failed"
    );
    assert.equal(formatProtocolSummary(null), "Server IPv4/IPv6 status is unavailable.");
});



test("aborts a stalled network protocol request", async () => {
    const originalFetch = global.fetch;
    let observedAbort = false;
    global.fetch = (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
            observedAbort = true;
            reject(new Error("request aborted"));
        }, { once: true });
    });

    try {
        assert.equal(await runNetworkProtocolTest(), null);
        assert.equal(observedAbort, true);
    } finally {
        global.fetch = originalFetch;
    }
});
