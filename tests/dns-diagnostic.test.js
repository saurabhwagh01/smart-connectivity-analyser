const test = require("node:test");
const assert = require("node:assert/strict");
const { formatDnsStatus } = require("../js/script.js");

test("shows a successful server DNS result and duration", () => {
    assert.equal(
        formatDnsStatus({ status: "ok", duration_ms: 12.3 }),
        "Server DNS: resolved in 12.3 ms."
    );
});

test("shows timeout without inventing a duration", () => {
    assert.equal(
        formatDnsStatus({
            status: "failed",
            failure_category: "timeout",
            duration_ms: null
        }),
        "Server DNS: lookup timed out."
    );
});

test("distinguishes DNS failure categories", () => {
    assert.equal(
        formatDnsStatus({
            status: "failed",
            failure_category: "not_found",
            duration_ms: 4
        }),
        "Server DNS: hostname not found in 4 ms."
    );
    assert.equal(
        formatDnsStatus({
            status: "failed",
            failure_category: "resolver_unavailable",
            duration_ms: 3
        }),
        "Server DNS: resolver unavailable in 3 ms."
    );
    assert.equal(
        formatDnsStatus({
            status: "failed",
            failure_category: "capacity_exhausted",
            duration_ms: null
        }),
        "Server DNS: diagnostic capacity reached."
    );
});

test("handles an unavailable API result", () => {
    assert.equal(
        formatDnsStatus(null),
        "Server DNS: status unavailable."
    );
});
