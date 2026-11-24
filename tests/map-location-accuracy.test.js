const { describe, test } = require("node:test");
const assert = require("node:assert/strict");

const {
    validateCoordinates,
    resolveLocationZoom,
    formatLocationAccuracy,
    resolveGeolocationErrorMessage
} = require("../js/script.js");

describe("Map Location Accuracy & Coordinate Validation", () => {

    describe("validateCoordinates", () => {
        test("accepts valid GPS coordinates", () => {
            const res = validateCoordinates(37.7749, -122.4194);
            assert.equal(res.valid, true);
            assert.equal(res.latitude, 37.7749);
            assert.equal(res.longitude, -122.4194);
        });

        test("accepts boundary coordinates (0, 0)", () => {
            const res = validateCoordinates(0, 0);
            assert.equal(res.valid, true);
            assert.equal(res.latitude, 0);
            assert.equal(res.longitude, 0);
        });

        test("accepts extremes (-90 to 90, -180 to 180)", () => {
            const northPole = validateCoordinates(90, 180);
            assert.equal(northPole.valid, true);

            const southPole = validateCoordinates(-90, -180);
            assert.equal(southPole.valid, true);
        });

        test("converts string numeric coordinates cleanly", () => {
            const res = validateCoordinates("19.0760", "72.8777");
            assert.equal(res.valid, true);
            assert.equal(res.latitude, 19.076);
            assert.equal(res.longitude, 72.8777);
        });

        test("rejects latitude out of bounds (> 90 or < -90)", () => {
            const tooNorth = validateCoordinates(90.1, 10);
            assert.equal(tooNorth.valid, false);
            assert.match(tooNorth.error, /Latitude/);

            const tooSouth = validateCoordinates(-91, 10);
            assert.equal(tooSouth.valid, false);
            assert.match(tooSouth.error, /Latitude/);
        });

        test("rejects longitude out of bounds (> 180 or < -180)", () => {
            const tooEast = validateCoordinates(10, 180.5);
            assert.equal(tooEast.valid, false);
            assert.match(tooEast.error, /Longitude/);

            const tooWest = validateCoordinates(10, -181);
            assert.equal(tooWest.valid, false);
            assert.match(tooWest.error, /Longitude/);
        });

        test("rejects non-numeric, null, undefined, and NaN coordinates", () => {
            assert.equal(validateCoordinates(null, 50).valid, false);
            assert.equal(validateCoordinates(50, null).valid, false);
            assert.equal(validateCoordinates(undefined, 50).valid, false);
            assert.equal(validateCoordinates("invalid", 50).valid, false);
            assert.equal(validateCoordinates(50, "invalid").valid, false);
            assert.equal(validateCoordinates(NaN, 50).valid, false);
            assert.equal(validateCoordinates(Infinity, 50).valid, false);
        });
    });

    describe("resolveLocationZoom", () => {
        test("returns high zoom for high precision (<= 100m)", () => {
            assert.equal(resolveLocationZoom(15), 17);
            assert.equal(resolveLocationZoom(100), 17);
        });

        test("returns intermediate zoom for medium accuracy (<= 500m)", () => {
            assert.equal(resolveLocationZoom(250), 15);
            assert.equal(resolveLocationZoom(500), 15);
        });

        test("returns moderate zoom for city-level accuracy (<= 1500m)", () => {
            assert.equal(resolveLocationZoom(1000), 14);
            assert.equal(resolveLocationZoom(1500), 14);
        });

        test("returns wide zoom for regional accuracy (<= 5000m)", () => {
            assert.equal(resolveLocationZoom(3000), 12);
            assert.equal(resolveLocationZoom(5000), 12);
        });

        test("returns overview zoom for poor accuracy (> 5000m)", () => {
            assert.equal(resolveLocationZoom(8000), 10);
            assert.equal(resolveLocationZoom(25000), 10);
        });

        test("returns default zoom for null, invalid or negative accuracy", () => {
            assert.equal(resolveLocationZoom(null), 16);
            assert.equal(resolveLocationZoom(-10), 16);
            assert.equal(resolveLocationZoom("unknown"), 16);
        });
    });

    describe("formatLocationAccuracy", () => {
        test("formats accuracy in meters when below 1000m", () => {
            assert.equal(formatLocationAccuracy(35), "±35 m");
            assert.equal(formatLocationAccuracy(12.4), "±12 m");
            assert.equal(formatLocationAccuracy(999), "±999 m");
        });

        test("formats accuracy in kilometers when 1000m or higher", () => {
            assert.equal(formatLocationAccuracy(1000), "±1.0 km");
            assert.equal(formatLocationAccuracy(2450), "±2.5 km");
            assert.equal(formatLocationAccuracy(15000), "±15.0 km");
        });

        test("handles unknown or negative accuracy cleanly", () => {
            assert.equal(formatLocationAccuracy(null), "±unknown");
            assert.equal(formatLocationAccuracy(undefined), "±unknown");
            assert.equal(formatLocationAccuracy(-5), "±unknown");
        });
    });

    describe("resolveGeolocationErrorMessage", () => {
        test("handles permission denied error (code 1)", () => {
            const msg = resolveGeolocationErrorMessage({ code: 1 });
            assert.match(msg, /Location permission denied/i);
            assert.match(msg, /browser/i);
        });

        test("handles position unavailable error (code 2)", () => {
            const msg = resolveGeolocationErrorMessage({ code: 2 });
            assert.match(msg, /Location information is unavailable/i);
            assert.match(msg, /GPS/i);
        });

        test("handles timeout error (code 3)", () => {
            const msg = resolveGeolocationErrorMessage({ code: 3 });
            assert.match(msg, /Location request timed out/i);
            assert.match(msg, /Retry Location/i);
        });

        test("handles numeric error codes directly", () => {
            assert.match(resolveGeolocationErrorMessage(1), /Location permission denied/i);
            assert.match(resolveGeolocationErrorMessage(2), /unavailable/i);
            assert.match(resolveGeolocationErrorMessage(3), /timed out/i);
        });

        test("handles fallback generic errors", () => {
            const msg = resolveGeolocationErrorMessage({ message: "Custom hardware failure" });
            assert.equal(msg, "Custom hardware failure");

            const emptyMsg = resolveGeolocationErrorMessage(null);
            assert.match(emptyMsg, /Unable to detect location/i);
        });
    });
});
