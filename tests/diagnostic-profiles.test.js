const { describe, test } = require("node:test");
const assert = require("node:assert/strict");

const {
    evaluateProfileResult,
    describeOutcome,
    loadDiagnosticProfiles,
    selectDiagnosticProfile,
    getSelectedProfile
} = require("../js/script.js");

const QUICK = {
    id: "quick",
    label: "Quick Check",
    checks: ["ping", "packet_loss"]
};

const DETAILED = {
    id: "detailed",
    label: "Detailed Diagnosis",
    checks: ["ping", "jitter", "packet_loss", "download", "upload"]
};

const STABILITY = {
    id: "stability",
    label: "Stability Test",
    checks: ["ping", "jitter", "packet_loss"]
};

const OK = { status: "ok" };

function backend(overrides = {}) {
    return {
        profile: "detailed",
        measured_at: "2026-11-24T10:00:00+00:00",
        ping_ms: 20.5,
        jitter_ms: 2.25,
        packet_loss: 0,
        checks: { ping: OK, jitter: OK, packet_loss: OK },
        ...overrides
    };
}

describe("Quick Check", () => {
    test("shows only its documented checks, all successful", () => {
        const result = evaluateProfileResult(
            QUICK,
            backend({
                checks: { ping: OK, packet_loss: OK },
                jitter_ms: 9.9 // must be ignored: quick does not include jitter
            }),
            null
        );

        assert.equal(result.state, "success");
        assert.deepEqual(
            result.rows.map((row) => row.check),
            ["ping", "packet_loss"]
        );
    });

    test("does not run or require bandwidth checks", () => {
        const result = evaluateProfileResult(
            QUICK,
            backend({ checks: { ping: OK, packet_loss: OK } }),
            null
        );

        assert.equal(result.failed.length, 0);
    });

    test("does not mark packet loss successful without a valid measurement", () => {
        const result = evaluateProfileResult(
            QUICK,
            backend({ packet_loss: null }),
            null
        );

        assert.equal(result.state, "partial");
        assert.deepEqual(result.failed, ["Packet loss"]);
        assert.equal(
            result.rows.find((row) => row.check === "packet_loss").status,
            "failed"
        );
    });

    test("accepts a measured zero packet-loss value", () => {
        const result = evaluateProfileResult(QUICK, backend({ packet_loss: 0 }), null);

        assert.equal(result.rows.find((row) => row.check === "packet_loss").status, "ok");
        assert.equal(result.rows.find((row) => row.check === "packet_loss").detail, "0.00 %");
    });

    test("does not invent a measurement timestamp when the backend omits it", () => {
        const result = evaluateProfileResult(
            QUICK,
            backend({ measured_at: undefined }),
            null
        );

        assert.equal(result.measuredAt, null);
    });
});

describe("Profile loading and selection", () => {
    test("loads profiles and selects only an available option", async () => {
        let requestedUrl;
        const profiles = [QUICK, DETAILED];
        const loaded = await loadDiagnosticProfiles(async (url, options) => {
            requestedUrl = url;
            assert.deepEqual(options, { cache: "no-store" });
            return { ok: true, json: async () => ({ profiles }) };
        });

        assert.match(requestedUrl, /diagnostic-profiles$/);
        assert.deepEqual(loaded, profiles);
        assert.equal(selectDiagnosticProfile("quick"), QUICK);
        assert.equal(getSelectedProfile(), QUICK);
        assert.equal(selectDiagnosticProfile("missing"), null);
        assert.equal(getSelectedProfile(), null);
    });

    test("clears a selected option when it is no longer available", async () => {
        await loadDiagnosticProfiles(async () => ({
            ok: true,
            json: async () => ({ profiles: [QUICK] })
        }));
        selectDiagnosticProfile("quick");

        await loadDiagnosticProfiles(async () => ({
            ok: true,
            json: async () => ({ profiles: [DETAILED] })
        }));

        assert.equal(getSelectedProfile(), null);
    });
});

describe("Detailed Diagnosis", () => {
    test("is successful when backend and bandwidth checks all succeed", () => {
        const result = evaluateProfileResult(
            DETAILED,
            backend(),
            { download: 48.2, upload: 12.4 }
        );

        assert.equal(result.state, "success");
        assert.equal(result.rows.length, 5);
        assert.equal(
            result.rows.find((r) => r.check === "download").detail,
            "48.20 Mbps"
        );
    });

    test("is a partial failure when bandwidth is unavailable", () => {
        const result = evaluateProfileResult(
            DETAILED,
            backend(),
            { download: null, upload: null }
        );

        assert.equal(result.state, "partial");
        assert.deepEqual(result.failed, ["Download speed", "Upload speed"]);
    });

    test("is a partial failure when only the backend is down", () => {
        const result = evaluateProfileResult(
            DETAILED,
            null,
            { download: 30, upload: 10 },
            "Ping measurement timed out."
        );

        assert.equal(result.state, "partial");
        assert.equal(
            result.rows.find((r) => r.check === "ping").detail,
            "Ping measurement timed out."
        );
    });
});

describe("Stability Test", () => {
    test("marks jitter as failed with the backend reason", () => {
        const result = evaluateProfileResult(
            STABILITY,
            backend({
                jitter_ms: null,
                checks: {
                    ping: OK,
                    jitter: {
                        status: "failed",
                        reason: "Jitter needs at least 2 ping replies."
                    },
                    packet_loss: OK
                }
            }),
            null
        );

        assert.equal(result.state, "partial");
        assert.deepEqual(result.failed, ["Jitter"]);
        assert.equal(
            result.rows.find((r) => r.check === "jitter").detail,
            "Jitter needs at least 2 ping replies."
        );
    });
});

describe("Error handling", () => {
    test("everything failed is an error, with the API message shown", () => {
        const result = evaluateProfileResult(
            QUICK,
            null,
            null,
            "Unknown diagnostic profile 'x'."
        );

        assert.equal(result.state, "error");
        assert.ok(
            result.rows.every(
                (row) =>
                    row.status === "failed" &&
                    row.detail === "Unknown diagnostic profile 'x'."
            )
        );
    });

    test("a missing check in the response is reported, never invented", () => {
        const result = evaluateProfileResult(
            QUICK,
            backend({ checks: { ping: OK } }), // packet_loss missing
            null
        );

        assert.equal(result.state, "partial");
        assert.deepEqual(result.failed, ["Packet loss"]);
    });

    test("falls back to a generic message when no error text exists", () => {
        const result = evaluateProfileResult(QUICK, null, null);

        assert.equal(
            result.rows[0].detail,
            "The backend did not return this check."
        );
    });
});

describe("Result summary message", () => {
    test("standard test (no profile) keeps the original wording", () => {
        assert.equal(
            describeOutcome(null, null),
            "Network test completed successfully."
        );
    });

    test("success", () => {
        assert.equal(
            describeOutcome(QUICK, { state: "success", failed: [] }),
            "Quick Check completed. All checks succeeded."
        );
    });

    test("partial failure lists the failed checks", () => {
        assert.equal(
            describeOutcome(DETAILED, {
                state: "partial",
                failed: ["Download speed", "Upload speed"]
            }),
            "Detailed Diagnosis finished, but 2 check(s) failed: Download speed, Upload speed."
        );
    });

    test("error", () => {
        assert.equal(
            describeOutcome(STABILITY, { state: "error", failed: [] }),
            "Stability Test failed. No check produced a result."
        );
    });
});

