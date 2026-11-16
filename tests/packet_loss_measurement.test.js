const test = require("node:test");
const assert = require("node:assert");

const {
    formatMetric,
    formatNetworkMetric,
    resolveDashboardDisplayState,
    measureBrowserLatency
} = require("../js/script.js");

test.describe("Packet Loss Measurement and Display Suite", () => {

    test.describe("measureBrowserLatency() probe packet loss calculation", () => {
        test("calculates 0.0% packet loss when all probes succeed", async () => {
            const originalFetch = global.fetch;
            global.fetch = async () => ({ ok: true, text: async () => "colo=DFW" });

            try {
                const result = await measureBrowserLatency(5);
                assert.ok(result.ping !== null);
                assert.ok(result.jitter !== null);
                assert.strictEqual(result.packetLoss, 0.0);
            } finally {
                global.fetch = originalFetch;
            }
        });

        test("calculates 20.0% packet loss when 1 of 5 probes fails", async () => {
            const originalFetch = global.fetch;
            let count = 0;
            global.fetch = async () => {
                count++;
                if (count === 3) throw new Error("Probe dropped");
                return { ok: true, text: async () => "colo=DFW" };
            };

            try {
                const result = await measureBrowserLatency(5);
                assert.strictEqual(result.packetLoss, 20.0);
            } finally {
                global.fetch = originalFetch;
            }
        });

        test("returns null packet loss and null latency when all probes fail", async () => {
            const originalFetch = global.fetch;
            global.fetch = async () => {
                throw new Error("Network offline");
            };

            try {
                const result = await measureBrowserLatency(5);
                assert.strictEqual(result.ping, null);
                assert.strictEqual(result.jitter, null);
                assert.strictEqual(result.packetLoss, null);
            } finally {
                global.fetch = originalFetch;
            }
        });
    });

    test.describe("Dashboard Packet Loss Display", () => {
        test("formats 0.0% packet loss on dashboard when test succeeds with 0 loss", () => {
            const state = resolveDashboardDisplayState({
                download: 50.0,
                upload: 15.0,
                ping: 25.0,
                jitter: 3.0,
                packetLoss: 0.0,
                score: 95
            });

            assert.strictEqual(state.packetLoss, "0.0");
        });

        test("formats measured non-zero packet loss on dashboard", () => {
            const state = resolveDashboardDisplayState({
                download: 50.0,
                upload: 15.0,
                ping: 25.0,
                jitter: 3.0,
                packetLoss: 2.5,
                score: 85
            });

            assert.strictEqual(state.packetLoss, "2.5");
        });

        test("displays 'Unavailable' only when packet loss measurement genuinely fails (null)", () => {
            const state = resolveDashboardDisplayState({
                download: 50.0,
                upload: 15.0,
                ping: 25.0,
                jitter: 3.0,
                packetLoss: null,
                score: 75
            });

            assert.strictEqual(state.packetLoss, "Unavailable");
        });

        test("displays 'Unavailable' when device is offline", () => {
            const state = resolveDashboardDisplayState(
                {
                    download: 50.0,
                    upload: 15.0,
                    ping: 25.0,
                    jitter: 3.0,
                    packetLoss: 0.0,
                    score: 95
                },
                { isOffline: true }
            );

            assert.strictEqual(state.packetLoss, "Unavailable");
        });
    });
});
