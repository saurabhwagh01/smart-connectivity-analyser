const { describe, it } = require("node:test");
const assert = require("node:assert");

const {
    resolveDashboardDisplayState,
    resolveConnectivityIndicator,
    setStartButtonBusy
} = require("../js/script.js");

describe("Run Test Loading State & Feedback Suite (#59)", () => {
    describe("resolveDashboardDisplayState during active testing (isTesting: true)", () => {
        it("preserves previously available results during testing instead of displaying 'Unavailable'", () => {
            const previousMetrics = {
                download: 85.4,
                upload: 22.1,
                ping: 15.0,
                jitter: 2.3,
                packetLoss: 0.0,
                score: 92
            };

            const state = resolveDashboardDisplayState(previousMetrics, {
                isOffline: false,
                isTesting: true,
                isHistoryRestored: false
            });

            // Previous metric numbers must be preserved
            assert.strictEqual(state.download, "85.4");
            assert.strictEqual(state.upload, "22.1");
            assert.strictEqual(state.ping, "15.0");
            assert.strictEqual(state.jitter, "2.3");
            assert.strictEqual(state.packetLoss, "0.0");
            assert.strictEqual(state.score, 92);

            // Subtitle must inform user that previous measurements remain visible
            assert.strictEqual(
                state.metricsSubtitle,
                "Testing network... (displaying previous measurements)"
            );

            // Indicator must reflect testing state
            assert.strictEqual(state.indicator.status, "Testing");
            assert.strictEqual(state.indicator.dotClass, "testing");
        });

        it("displays 'Measuring...' instead of misleading 'Unavailable' when no prior metrics exist", () => {
            const initialMetrics = {
                download: null,
                upload: null,
                ping: null,
                jitter: null,
                packetLoss: null,
                score: 0
            };

            const state = resolveDashboardDisplayState(initialMetrics, {
                isOffline: false,
                isTesting: true,
                isHistoryRestored: false
            });

            assert.strictEqual(state.download, "Measuring...");
            assert.strictEqual(state.upload, "Measuring...");
            assert.strictEqual(state.ping, "Measuring...");
            assert.strictEqual(state.jitter, "Measuring...");
            assert.strictEqual(state.packetLoss, "Measuring...");

            assert.strictEqual(
                state.metricsSubtitle,
                "Testing network... (measurements in progress)"
            );

            assert.strictEqual(state.indicator.status, "Testing");
            assert.strictEqual(state.indicator.dotClass, "testing");
        });

        it("displays 'Unavailable' only when device is actually offline, even if isTesting is true", () => {
            const state = resolveDashboardDisplayState(
                { download: 50.0, upload: 10.0, score: 75 },
                { isOffline: true, isTesting: true }
            );

            assert.strictEqual(state.download, "Unavailable");
            assert.strictEqual(state.upload, "Unavailable");
            assert.strictEqual(state.score, 0);
            assert.strictEqual(state.indicator.status, "Offline");
            assert.strictEqual(state.indicator.dotClass, "disconnected");
        });
    });

    describe("setStartButtonBusy()", () => {
        it("properly updates aria attributes, label, icon and loading class when busy is true", () => {
            const mockAttrs = {};
            const mockClasses = new Set();
            const mockIcon = {
                className: "fa-solid fa-bolt",
                dataset: {}
            };
            const mockLabel = { textContent: "Start Test" };

            // Mock DOM query
            const mockButton = {
                setAttribute: (name, val) => {
                    mockAttrs[name] = val;
                },
                classList: {
                    add: (cls) => mockClasses.add(cls),
                    remove: (cls) => mockClasses.delete(cls)
                },
                querySelector: (sel) => (sel === "i" ? mockIcon : null)
            };

            global.document = {
                getElementById: (id) => (id === "startTestLabel" ? mockLabel : null)
            };
            global.$ = (id) => global.document.getElementById(id);

            setStartButtonBusy(mockButton, true);

            assert.strictEqual(mockAttrs["aria-busy"], "true");
            assert.strictEqual(mockAttrs["aria-disabled"], "true");
            assert.strictEqual(mockLabel.textContent, "Testing...");
            assert.strictEqual(mockIcon.className, "fa-solid fa-circle-notch fa-spin");
            assert.strictEqual(mockIcon.dataset.prevClass, "fa-solid fa-bolt");
            assert.strictEqual(mockClasses.has("loading"), true);
        });

        it("properly restores aria attributes, label, icon and removes loading class when busy is false", () => {
            const mockAttrs = { "aria-busy": "true", "aria-disabled": "true" };
            const mockClasses = new Set(["loading"]);
            const mockIcon = {
                className: "fa-solid fa-circle-notch fa-spin",
                dataset: { prevClass: "fa-solid fa-bolt" }
            };
            const mockLabel = { textContent: "Testing..." };

            const mockButton = {
                setAttribute: (name, val) => {
                    mockAttrs[name] = val;
                },
                classList: {
                    add: (cls) => mockClasses.add(cls),
                    remove: (cls) => mockClasses.delete(cls)
                },
                querySelector: (sel) => (sel === "i" ? mockIcon : null)
            };

            global.document = {
                getElementById: (id) => (id === "startTestLabel" ? mockLabel : null)
            };
            global.$ = (id) => global.document.getElementById(id);

            setStartButtonBusy(mockButton, false);

            assert.strictEqual(mockAttrs["aria-busy"], "false");
            assert.strictEqual(mockAttrs["aria-disabled"], "false");
            assert.strictEqual(mockLabel.textContent, "Start Test");
            assert.strictEqual(mockIcon.className, "fa-solid fa-bolt");
            assert.strictEqual(mockClasses.has("loading"), false);
        });
    });
});
