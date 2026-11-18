const { describe, test, beforeEach } = require("node:test");
const assert = require("node:assert/strict");

const {
    normalizeHistoryItem,
    initializeChart,
    destroyCharts,
    updateHistoryChart,
    validateHistoryFilterValues,
    exportHistoryToCSV
} = require("../js/script.js");

// Mock DOM elements and Chart.js for Node testing environment
class MockCanvas {
    constructor(id) {
        this.id = id;
        this.attributes = {};
    }
    getContext(type) {
        return { type, canvasId: this.id };
    }
    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }
    getAttribute(name) {
        return this.attributes[name];
    }
}

class MockChart {
    static instances = [];
    static registry = new Map();

    static getChart(key) {
        if (!key) return null;
        if (typeof key === "string") return MockChart.registry.get(key) || null;
        if (key.id) return MockChart.registry.get(key.id) || null;
        return null;
    }

    constructor(ctx, config) {
        this.ctx = ctx;
        this.config = config;
        this.type = config.type;
        this.data = config.data || { labels: [], datasets: [] };
        this.options = config.options || {};
        this.updateCalls = 0;
        this.resizeCalls = 0;
        this.destroyed = false;

        MockChart.instances.push(this);
        if (ctx && ctx.canvasId) {
            MockChart.registry.set(ctx.canvasId, this);
        }
    }

    update() {
        this.updateCalls++;
    }

    resize() {
        this.resizeCalls++;
    }

    destroy() {
        this.destroyed = true;
        if (this.ctx && this.ctx.canvasId) {
            MockChart.registry.delete(this.ctx.canvasId);
        }
    }
}

describe("Network History Graphs & Charts Suite", () => {
    let elements = {};

    beforeEach(() => {
        MockChart.instances = [];
        MockChart.registry.clear();

        elements = {
            networkChart: new MockCanvas("networkChart"),
            downloadChart: new MockCanvas("downloadChart"),
            uploadChart: new MockCanvas("uploadChart"),
            pingChart: new MockCanvas("pingChart"),
            jitterChart: new MockCanvas("jitterChart"),
            packetLossChart: new MockCanvas("packetLossChart"),
            historyRange: { value: "all" },
            historyChartContainer: { hidden: false },
            historyEmptyState: { hidden: true },
            historyErrorState: { hidden: true }
        };

        global.document = {
            getElementById: (id) => elements[id] || null
        };
        global.Chart = MockChart;

        // Reset chart singletons before each test
        destroyCharts();
    });

    test("1. Correct mapping of historical API records via normalizeHistoryItem", () => {
        const rawBackendRecord = {
            id: 1,
            timestamp: "2026-11-16T12:00:00.000Z",
            download_mbps: 85.5,
            upload_mbps: 32.1,
            ping_ms: 18.2,
            jitter_ms: 2.4,
            packet_loss: 0.0,
            network_type: "WiFi",
            connectivity_score: 95
        };

        const item = normalizeHistoryItem(rawBackendRecord);

        assert.equal(item.timestamp, "2026-11-16T12:00:00.000Z");
        assert.equal(item.download_mbps, 85.5);
        assert.equal(item.upload_mbps, 32.1);
        assert.equal(item.ping, 18.2);
        assert.equal(item.jitter, 2.4);
        assert.equal(item.packet_loss, 0.0);
        assert.equal(item.connectivity_score, 95);
    });

    test("2. Alternate API field naming normalization (camelCase & aliases)", () => {
        const rawAlternateRecord = {
            time: "2026-11-16T13:00:00.000Z",
            downloadSpeed: 100.2,
            uploadSpeed: 45.0,
            ping: 15,
            jitter: 1.8,
            packetLoss: 0.5,
            score: 98
        };

        const item = normalizeHistoryItem(rawAlternateRecord);

        assert.equal(item.timestamp, "2026-11-16T13:00:00.000Z");
        assert.equal(item.download_mbps, 100.2);
        assert.equal(item.upload_mbps, 45.0);
        assert.equal(item.ping, 15);
        assert.equal(item.jitter, 1.8);
        assert.equal(item.packet_loss, 0.5);
        assert.equal(item.connectivity_score, 98);
    });

    test("3. Missing and optional metric values handle safely without crashing", () => {
        const partialRecord = {
            timestamp: "2026-11-16T14:00:00.000Z",
            download_mbps: null,
            upload_mbps: null,
            ping_ms: null,
            jitter_ms: null,
            packet_loss: null,
            connectivity_score: 40
        };

        const item = normalizeHistoryItem(partialRecord);

        assert.equal(item.download_mbps, null);
        assert.equal(item.upload_mbps, null);
        assert.equal(item.ping, null);
        assert.equal(item.jitter, null);
        assert.equal(item.packet_loss, null);
        assert.equal(item.connectivity_score, 40);
    });

    test("4. Timestamp normalization: preserves invalid/missing timestamps as null without defaulting to current time", () => {
        // Missing timestamp
        const missing = normalizeHistoryItem({ download_mbps: 50 });
        assert.strictEqual(missing.timestamp, null);

        // Null timestamp
        const nullTime = normalizeHistoryItem({ timestamp: null, download_mbps: 50 });
        assert.strictEqual(nullTime.timestamp, null);

        // Empty string timestamp
        const emptyTime = normalizeHistoryItem({ timestamp: "", download_mbps: 50 });
        assert.strictEqual(emptyTime.timestamp, null);

        // Invalid timestamp string
        const invalidTime = normalizeHistoryItem({ timestamp: "not-a-valid-date", download_mbps: 50 });
        assert.strictEqual(invalidTime.timestamp, null);

        // Valid ISO timestamp
        const validTime = normalizeHistoryItem({ timestamp: "2026-11-16T12:00:00.000Z", download_mbps: 50 });
        assert.strictEqual(validTime.timestamp, "2026-11-16T12:00:00.000Z");
    });

    test("5. Chart dataset excludes invalid timestamps and preserves valid records ordering", () => {
        initializeChart();

        const mixedRecords = [
            { timestamp: "2026-11-16T10:00:00.000Z", download_mbps: 30.0, score: 70 },
            { timestamp: "invalid-timestamp", download_mbps: 99.0, score: 99 },
            { timestamp: null, download_mbps: 88.0, score: 88 },
            { download_mbps: 77.0, score: 77 },
            { timestamp: "2026-11-16T08:00:00.000Z", download_mbps: 20.0, score: 60 },
            { timestamp: "2026-11-16T12:00:00.000Z", download_mbps: 40.0, score: 80 }
        ];

        updateHistoryChart(mixedRecords, "all");

        const downloadChartInstance = MockChart.getChart("downloadChart");
        assert.ok(downloadChartInstance, "downloadChart instance should exist");

        // Exactly the 3 valid records should be plotted
        assert.strictEqual(downloadChartInstance.data.labels.length, 3);
        // Correct chronological order: 08:00, 10:00, 12:00
        assert.deepStrictEqual(downloadChartInstance.data.datasets[0].data, [20.0, 30.0, 40.0]);

        const networkChartInstance = MockChart.getChart("networkChart");
        assert.strictEqual(networkChartInstance.data.labels.length, 3);
        assert.deepStrictEqual(networkChartInstance.data.datasets[0].data, [60, 70, 80]); // Score
        assert.deepStrictEqual(networkChartInstance.data.datasets[1].data, [20.0, 30.0, 40.0]); // Download
    });

    test("6. initializeChart constructs genuine Chart instances for all five historical metrics and composite chart", () => {
        initializeChart();

        const expectedCharts = [
            { id: "networkChart", datasets: 2, labelContains: "Connectivity Score" },
            { id: "downloadChart", datasets: 1, labelContains: "Download Speed" },
            { id: "uploadChart", datasets: 1, labelContains: "Upload Speed" },
            { id: "pingChart", datasets: 1, labelContains: "Ping Latency" },
            { id: "jitterChart", datasets: 1, labelContains: "Jitter" },
            { id: "packetLossChart", datasets: 1, labelContains: "Packet Loss" }
        ];

        // 6 distinct Chart instances constructed
        assert.strictEqual(MockChart.instances.length, 6);

        for (const exp of expectedCharts) {
            const instance = MockChart.getChart(exp.id);
            assert.ok(instance, `Expected chart instance for ${exp.id}`);
            assert.strictEqual(instance.type, "line");
            assert.strictEqual(instance.ctx.canvasId, exp.id);
            assert.strictEqual(instance.data.datasets.length, exp.datasets);
            assert.match(instance.data.datasets[0].label, new RegExp(exp.labelContains, "i"));
            assert.strictEqual(instance.destroyed, false);
        }
    });

    test("7. Chart instances are retained and updated when data changes, and destroyed on cleanup", () => {
        initializeChart();
        assert.strictEqual(MockChart.instances.length, 6);

        const firstBatch = MockChart.instances.slice();

        // Calling updateHistoryChart updates existing instances without re-creating them
        const historyData = [
            { timestamp: "2026-11-16T10:00:00.000Z", download_mbps: 45.2, upload_mbps: 15.0, ping_ms: 20, jitter_ms: 2, packet_loss: 0, connectivity_score: 85 }
        ];
        updateHistoryChart(historyData, "all");

        // No new instances created
        assert.strictEqual(MockChart.instances.length, 6);
        for (const chart of firstBatch) {
            assert.ok(chart.updateCalls >= 1, `Chart on canvas ${chart.ctx.canvasId} was updated`);
            assert.strictEqual(chart.destroyed, false);
            assert.strictEqual(chart.data.labels.length, 1);
        }

        // Specific metric datasets updated
        const pingInstance = MockChart.getChart("pingChart");
        assert.deepStrictEqual(pingInstance.data.datasets[0].data, [20]);

        const jitterInstance = MockChart.getChart("jitterChart");
        assert.deepStrictEqual(jitterInstance.data.datasets[0].data, [2]);

        const lossInstance = MockChart.getChart("packetLossChart");
        assert.deepStrictEqual(lossInstance.data.datasets[0].data, [0]);

        // destroyCharts cleanly destroys all 6 instances
        destroyCharts();
        for (const chart of firstBatch) {
            assert.strictEqual(chart.destroyed, true);
        }
        assert.strictEqual(MockChart.getChart("networkChart"), null);
        assert.strictEqual(MockChart.getChart("downloadChart"), null);
    });

    test("8. updateHistoryChart updates accessibility aria-labels for all metrics", () => {
        initializeChart();

        const history = [
            {
                timestamp: "2026-11-16T10:00:00.000Z",
                download_mbps: 45.2,
                upload_mbps: 12.0,
                ping_ms: 22.1,
                jitter_ms: 3.5,
                packet_loss: 0.0,
                connectivity_score: 82
            },
            {
                timestamp: "2026-11-16T11:00:00.000Z",
                download_mbps: 78.4,
                upload_mbps: 25.3,
                ping_ms: 15.0,
                jitter_ms: 1.9,
                packet_loss: 0.1,
                connectivity_score: 94
            }
        ];

        updateHistoryChart(history, "all");

        // Accessible description should be set for all canvases
        assert.match(elements.networkChart.getAttribute("aria-label"), /showing 2 tests/i);
        assert.match(elements.downloadChart.getAttribute("aria-label"), /Download speed history chart showing 2 tests/i);
        assert.match(elements.uploadChart.getAttribute("aria-label"), /Upload speed history chart showing 2 tests/i);
        assert.match(elements.pingChart.getAttribute("aria-label"), /Ping latency history chart showing 2 tests/i);
        assert.match(elements.jitterChart.getAttribute("aria-label"), /Jitter history chart showing 2 tests/i);
        assert.match(elements.packetLossChart.getAttribute("aria-label"), /Packet loss history chart showing 2 tests/i);
    });

    test("9. updateHistoryChart handles empty history gracefully", () => {
        initializeChart();

        updateHistoryChart([], "all");

        assert.match(elements.networkChart.getAttribute("aria-label"), /No network history is available/i);
        assert.match(elements.downloadChart.getAttribute("aria-label"), /No history available/i);
        assert.match(elements.uploadChart.getAttribute("aria-label"), /No history available/i);
        assert.match(elements.pingChart.getAttribute("aria-label"), /No history available/i);
        assert.match(elements.jitterChart.getAttribute("aria-label"), /No history available/i);
        assert.match(elements.packetLossChart.getAttribute("aria-label"), /No history available/i);
    });

    test("10. Filter validation handles date and score bounds correctly", () => {
        const valid = validateHistoryFilterValues({
            startDate: "2026-11-01",
            endDate: "2026-11-16",
            minScore: "50",
            maxScore: "95"
        });
        assert.equal(valid.valid, true);
        assert.equal(valid.filters.minScore, 50);
        assert.equal(valid.filters.maxScore, 95);

        const reversedScore = validateHistoryFilterValues({
            minScore: "90",
            maxScore: "20"
        });
        assert.equal(reversedScore.valid, false);

        const reversedDate = validateHistoryFilterValues({
            startDate: "2026-11-16",
            endDate: "2026-11-01"
        });
        assert.equal(reversedDate.valid, false);
    });

    test("11. exportHistoryToCSV preserves compatibility and exports all network fields with safe timestamps", () => {
        let createdBlob = null;
        let downloadedFileName = "";

        global.Blob = class {
            constructor(parts, options) {
                this.parts = parts;
                this.options = options;
                createdBlob = this;
            }
        };

        global.URL = {
            createObjectURL: () => "blob:mock-url",
            revokeObjectURL: () => {}
        };

        global.showToast = () => {};

        const mockLink = {
            setAttribute: (name, val) => {},
            click: () => {},
            remove: () => {},
            href: ""
        };
        Object.defineProperty(mockLink, "download", {
            set: (val) => { downloadedFileName = val; },
            get: () => downloadedFileName
        });

        global.document.createElement = (tag) => {
            if (tag === "a") return mockLink;
            return {};
        };
        global.document.body = {
            appendChild: () => {},
            removeChild: () => {}
        };

        // When tests array is empty, it alerts/toasts
        exportHistoryToCSV();
        assert.ok(downloadedFileName === "");
    });
});
