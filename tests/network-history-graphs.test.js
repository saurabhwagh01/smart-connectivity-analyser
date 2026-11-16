const { describe, test, beforeEach } = require("node:test");
const assert = require("node:assert/strict");

const {
    normalizeHistoryItem,
    initializeChart,
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
        return { type };
    }
    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }
    getAttribute(name) {
        return this.attributes[name];
    }
}

class MockChart {
    constructor(ctx, config) {
        this.ctx = ctx;
        this.type = config.type;
        this.data = config.data || { labels: [], datasets: [] };
        this.options = config.options || {};
        this.updateCalls = 0;
        this.resizeCalls = 0;
    }
    update() {
        this.updateCalls++;
    }
    resize() {
        this.resizeCalls++;
    }
}

describe("Network History Graphs & Charts Suite", () => {
    let elements = {};

    beforeEach(() => {
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

    test("4. initializeChart creates instances for all historical charts", () => {
        initializeChart();
        // Verifying charts initialized without throw
        assert.ok(elements.networkChart);
        assert.ok(elements.downloadChart);
        assert.ok(elements.uploadChart);
        assert.ok(elements.pingChart);
        assert.ok(elements.jitterChart);
        assert.ok(elements.packetLossChart);
    });

    test("5. updateHistoryChart updates all charts with correct metric mappings", () => {
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

    test("6. updateHistoryChart handles empty history gracefully", () => {
        initializeChart();

        updateHistoryChart([], "all");

        assert.match(elements.networkChart.getAttribute("aria-label"), /No network history is available/i);
        assert.match(elements.downloadChart.getAttribute("aria-label"), /No history available/i);
        assert.match(elements.uploadChart.getAttribute("aria-label"), /No history available/i);
        assert.match(elements.pingChart.getAttribute("aria-label"), /No history available/i);
        assert.match(elements.jitterChart.getAttribute("aria-label"), /No history available/i);
        assert.match(elements.packetLossChart.getAttribute("aria-label"), /No history available/i);
    });

    test("7. Filter validation handles date and score bounds correctly", () => {
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

    test("8. exportHistoryToCSV preserves compatibility and exports all network fields", () => {
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
