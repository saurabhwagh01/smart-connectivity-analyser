const test = require("node:test");
const assert = require("node:assert/strict");

const {
    normalizeForecastResponse,
    resolveForecastRiskMeta,
    formatForecastRange,
    renderForecastSection
} = require("../js/script.js");

test("normalizeForecastResponse rejects empty or invalid payloads", () => {
    assert.equal(normalizeForecastResponse(null), null);
    assert.equal(normalizeForecastResponse({}), null);
    assert.equal(normalizeForecastResponse({ horizons: [] }), null);
    assert.equal(normalizeForecastResponse({ horizons: [{ horizon: "1h" }] }), null);
});

test("normalizeForecastResponse accepts valid multi-horizon forecast payload", () => {
    const payload = {
        success: true,
        generated_at: "2026-11-26T18:00:00+00:00",
        history_summary: { total_records: 8, fallback_used: false },
        degradation_risk: { level: "Moderate", score: 42.5, reasons: ["Latency rising"] },
        horizons: [
            {
                horizon: "1h",
                hours_ahead: 1,
                degradation_risk: { level: "Low", score: 20 },
                metrics: {
                    connectivity_score: { predicted: 78.4, lower: 71.0, upper: 85.8, unit: "/100" }
                }
            }
        ]
    };

    const normalized = normalizeForecastResponse(payload);
    assert.ok(normalized);
    assert.equal(normalized.horizons.length, 1);
    assert.equal(normalized.degradation_risk.level, "Moderate");
});

test("resolveForecastRiskMeta maps risk levels to accessible labels and icons", () => {
    assert.deepEqual(resolveForecastRiskMeta("Low"), {
        key: "low",
        label: "Low Risk",
        iconClass: "fa-solid fa-circle-check"
    });
    assert.deepEqual(resolveForecastRiskMeta("Moderate"), {
        key: "moderate",
        label: "Moderate Risk",
        iconClass: "fa-solid fa-circle-exclamation"
    });
    assert.deepEqual(resolveForecastRiskMeta("High"), {
        key: "high",
        label: "High Risk",
        iconClass: "fa-solid fa-triangle-exclamation"
    });
    assert.deepEqual(resolveForecastRiskMeta("Insufficient Data"), {
        key: "insufficient",
        label: "Insufficient Data",
        iconClass: "fa-solid fa-circle-info"
    });
    assert.equal(resolveForecastRiskMeta("unknown").key, "unavailable");
});

test("formatForecastRange formats point forecast and confidence bounds safely", () => {
    assert.equal(
        formatForecastRange({ predicted: 79.4, lower: 73.2, upper: 85.6, unit: "/100" }, 1),
        "79.4 /100 (73.2 – 85.6)"
    );
    assert.equal(
        formatForecastRange({ predicted: null, lower: null, upper: null, unit: "/100" }, 1),
        "Unavailable"
    );
    assert.equal(formatForecastRange(null, 1), "Unavailable");
});

test("renderForecastSection displays insufficient-data state when no history exists", () => {
    const makeEl = () => ({
        dataset: {},
        textContent: "",
        className: "",
        hidden: false,
        children: [],
        get firstChild() {
            return this.children[0] || null;
        },
        appendChild(node) {
            this.children.push(node);
            return node;
        },
        removeChild(node) {
            const idx = this.children.indexOf(node);
            if (idx >= 0) this.children.splice(idx, 1);
            return node;
        },
        setAttribute() {}
    });

    const elements = {
        forecastRiskBadge: makeEl(),
        forecastRiskIcon: makeEl(),
        forecastRiskText: makeEl(),
        forecastStatus: makeEl(),
        forecastHorizons: makeEl(),
        forecastRiskReasons: makeEl(),
        forecastChartContainer: makeEl(),
        forecastChart: makeEl()
    };

    const originalDocument = global.document;
    global.document = {
        getElementById: (id) => elements[id] || null,
        createElement: () => makeEl()
    };

    try {
        renderForecastSection({
            success: true,
            history_summary: { total_records: 0, fallback_used: true },
            degradation_risk: {
                level: "Insufficient Data",
                score: null,
                reasons: ["Not enough historical measurements yet to generate a trend forecast."]
            },
            horizons: [
                {
                    horizon: "1h",
                    hours_ahead: 1,
                    degradation_risk: { level: "Insufficient Data", score: null },
                    metrics: { connectivity_score: { predicted: null, unit: "/100" } }
                }
            ]
        });

        assert.equal(elements.forecastRiskBadge.dataset.risk, "insufficient");
        assert.equal(elements.forecastRiskText.textContent, "Insufficient Data");
        assert.equal(elements.forecastHorizons.children.length, 0);
        assert.equal(elements.forecastChartContainer.hidden, true);
        assert.match(elements.forecastStatus.textContent, /Not enough historical measurements/i);
    } finally {
        global.document = originalDocument;
    }
});

test("renderForecastSection displays Insufficient Data for sparse-history fallback in overall badge and horizon cards", () => {
    const makeEl = () => ({
        dataset: {},
        textContent: "",
        className: "",
        hidden: false,
        children: [],
        get firstChild() {
            return this.children[0] || null;
        },
        appendChild(node) {
            this.children.push(node);
            return node;
        },
        removeChild(node) {
            const idx = this.children.indexOf(node);
            if (idx >= 0) this.children.splice(idx, 1);
            return node;
        },
        append(...nodes) {
            for (const n of nodes) this.appendChild(n);
        },
        setAttribute() {}
    });

    const elements = {
        forecastRiskBadge: makeEl(),
        forecastRiskIcon: makeEl(),
        forecastRiskText: makeEl(),
        forecastStatus: makeEl(),
        forecastHorizons: makeEl(),
        forecastRiskReasons: makeEl(),
        forecastChartContainer: makeEl(),
        forecastChart: makeEl()
    };

    const originalDocument = global.document;
    global.document = {
        getElementById: (id) => elements[id] || null,
        createElement: () => makeEl()
    };

    try {
        renderForecastSection({
            success: true,
            history_summary: { total_records: 1, fallback_used: true, sufficient_history: false },
            degradation_risk: {
                level: "Insufficient Data",
                score: null,
                reasons: ["Forecast uses sparse-history fallback; accuracy will improve as more tests are recorded."]
            },
            horizons: [
                {
                    horizon: "1h",
                    hours_ahead: 1,
                    degradation_risk: { level: "Insufficient Data", score: null },
                    metrics: {
                        connectivity_score: { predicted: 80.0, lower: 72.0, upper: 88.0, unit: "/100" }
                    }
                },
                {
                    horizon: "6h",
                    hours_ahead: 6,
                    degradation_risk: { level: "Insufficient Data", score: null },
                    metrics: {
                        connectivity_score: { predicted: 80.0, lower: 68.0, upper: 92.0, unit: "/100" }
                    }
                }
            ]
        });

        assert.equal(elements.forecastRiskBadge.dataset.risk, "insufficient");
        assert.equal(elements.forecastRiskText.textContent, "Insufficient Data");
        assert.equal(elements.forecastHorizons.children.length, 2);

        for (const card of elements.forecastHorizons.children) {
            const header = card.children[0];
            assert.ok(header);
            const miniBadge = header.children.find((c) => c.className === "forecast-risk-badge");
            assert.ok(miniBadge);
            assert.equal(miniBadge.dataset.risk, "insufficient");
            const labelSpan = miniBadge.children.find((c) => c.textContent === "Insufficient Data");
            assert.ok(labelSpan);
        }
    } finally {
        global.document = originalDocument;
    }
});
