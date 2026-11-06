
const { describe, test } = require("node:test");
const assert = require("node:assert/strict");

const {
    validateHistoryFilterValues
} = require("../js/script.js");


describe("Network history filter validation", () => {

    test("accepts empty filters", () => {
        const result = validateHistoryFilterValues({});

        assert.equal(result.valid, true);
    });

    test("accepts a valid date range", () => {
        const result = validateHistoryFilterValues({
            startDate: "2026-11-01",
            endDate: "2026-11-05"
        });

        assert.equal(result.valid, true);
    });

    test("rejects reversed date ranges", () => {
        const result = validateHistoryFilterValues({
            startDate: "2026-11-05",
            endDate: "2026-11-01"
        });

        assert.equal(result.valid, false);
    });

    test("rejects invalid calendar dates", () => {
        const result = validateHistoryFilterValues({
            startDate: "2026-13-40"
        });

        assert.equal(result.valid, false);
    });

    test("accepts score boundaries", () => {
        const result = validateHistoryFilterValues({
            minScore: "0",
            maxScore: "100"
        });

        assert.equal(result.valid, true);
    });

    test("rejects scores outside the allowed range", () => {
        const result = validateHistoryFilterValues({
            minScore: "-5"
        });

        assert.equal(result.valid, false);
    });

    test("rejects non-numeric scores", () => {
        const result = validateHistoryFilterValues({
            maxScore: "excellent"
        });

        assert.equal(result.valid, false);
    });

    test("rejects minimum score greater than maximum score", () => {
        const result = validateHistoryFilterValues({
            minScore: "90",
            maxScore: "60"
        });

        assert.equal(result.valid, false);
    });

    test("accepts decimal scores", () => {
        const result = validateHistoryFilterValues({
            minScore: "65.5",
            maxScore: "89.9"
        });

        assert.equal(result.valid, true);
        assert.equal(result.filters.minScore, 65.5);
        assert.equal(result.filters.maxScore, 89.9);
    });

});
