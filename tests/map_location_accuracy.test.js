/**
 * Tests for Geolocation Accuracy, Map Visuals, Coordinate Validation, and UI States
 * Run with: node --test tests/map_location_accuracy.test.js
 */

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const {
    isValidCoordinate,
    calculateMapZoomForAccuracy,
    detectLocation,
    updateUserLocationVisuals,
    clearUserLocationVisuals
} = require("../js/script.js");

function createMockElement() {
    return {
        textContent: "",
        innerHTML: "",
        hidden: false,
        disabled: false,
        attributes: {},
        classList: {
            classes: new Set(),
            add(...t) { t.forEach((c) => this.classes.add(c)); },
            remove(...t) { t.forEach((c) => this.classes.delete(c)); },
            contains(c) { return this.classes.has(c); }
        },
        setAttribute(k, v) { this.attributes[k] = String(v); },
        removeAttribute(k) { delete this.attributes[k]; },
        getAttribute(k) { return this.attributes[k]; },
        addEventListener() {}
    };
}

function withMockEnv(navObj, fn) {
    const originalNavDescriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
    const originalDoc = global.document;
    const originalL = global.L;

    const dom = {
        locationResult: createMockElement(),
        detectLocation: createMockElement(),
        connectivityMap: createMockElement(),
        toast: createMockElement(),
        "toast-message": createMockElement()
    };

    global.document = {
        readyState: "loading",
        getElementById(id) {
            return dom[id] || null;
        },
        addEventListener() {}
    };

    Object.defineProperty(globalThis, "navigator", {
        value: navObj,
        configurable: true,
        writable: true
    });

    const restore = () => {
        if (originalNavDescriptor) {
            Object.defineProperty(globalThis, "navigator", originalNavDescriptor);
        } else {
            delete globalThis.navigator;
        }
        global.document = originalDoc;
        global.L = originalL;
    };

    try {
        const result = fn({ dom });
        restore();
        return result;
    } catch (err) {
        restore();
        throw err;
    }
}

describe("Coordinate Validation (isValidCoordinate)", () => {
    it("accepts valid GPS coordinates around the globe", () => {
        assert.equal(isValidCoordinate(19.076, 72.8777), true); // Mumbai
        assert.equal(isValidCoordinate(0, 0), true); // Equator / Prime Meridian
        assert.equal(isValidCoordinate(90, 180), true); // Max bounds
        assert.equal(isValidCoordinate(-90, -180), true); // Min bounds
        assert.equal(isValidCoordinate(37.7749, -122.4194), true); // San Francisco
        assert.equal(isValidCoordinate(-33.8688, 151.2093), true); // Sydney
    });

    it("rejects latitude out of range (> 90 or < -90)", () => {
        assert.equal(isValidCoordinate(90.0001, 50), false);
        assert.equal(isValidCoordinate(-90.0001, 50), false);
        assert.equal(isValidCoordinate(180, 50), false);
        assert.equal(isValidCoordinate(-120, 50), false);
    });

    it("rejects longitude out of range (> 180 or < -180)", () => {
        assert.equal(isValidCoordinate(50, 180.0001), false);
        assert.equal(isValidCoordinate(50, -180.0001), false);
        assert.equal(isValidCoordinate(50, 240), false);
        assert.equal(isValidCoordinate(50, -200), false);
    });

    it("rejects non-numeric, NaN, null, and non-finite values", () => {
        assert.equal(isValidCoordinate(NaN, 50), false);
        assert.equal(isValidCoordinate(50, NaN), false);
        assert.equal(isValidCoordinate(Infinity, 50), false);
        assert.equal(isValidCoordinate(50, -Infinity), false);
        assert.equal(isValidCoordinate(null, 50), false);
        assert.equal(isValidCoordinate(50, undefined), false);
        assert.equal(isValidCoordinate("19.076", "72.877"), false);
        assert.equal(isValidCoordinate({}, []), false);
    });
});

describe("Adaptive Map Zoom based on Reported Accuracy (calculateMapZoomForAccuracy)", () => {
    it("zooms in tightly (17) for high-precision GPS (<= 50m)", () => {
        assert.equal(calculateMapZoomForAccuracy(5), 17);
        assert.equal(calculateMapZoomForAccuracy(25), 17);
        assert.equal(calculateMapZoomForAccuracy(50), 17);
    });

    it("zooms to neighborhood level (16) for moderate accuracy (<= 200m)", () => {
        assert.equal(calculateMapZoomForAccuracy(60), 16);
        assert.equal(calculateMapZoomForAccuracy(150), 16);
        assert.equal(calculateMapZoomForAccuracy(200), 16);
    });

    it("zooms to district level (14) for low accuracy (<= 1000m)", () => {
        assert.equal(calculateMapZoomForAccuracy(500), 14);
        assert.equal(calculateMapZoomForAccuracy(1000), 14);
    });

    it("zooms to city level (12) for cell-tower accuracy (<= 5000m)", () => {
        assert.equal(calculateMapZoomForAccuracy(2500), 12);
        assert.equal(calculateMapZoomForAccuracy(5000), 12);
    });

    it("zooms out to regional level (10) for coarse or IP-based location (> 5000m)", () => {
        assert.equal(calculateMapZoomForAccuracy(10000), 10);
    });

    it("defaults to 16 for invalid or missing accuracy numbers", () => {
        assert.equal(calculateMapZoomForAccuracy(null), 16);
        assert.equal(calculateMapZoomForAccuracy(undefined), 16);
        assert.equal(calculateMapZoomForAccuracy(0), 16);
        assert.equal(calculateMapZoomForAccuracy(-5), 16);
    });
});

describe("Geolocation Lifecycle and UI States (detectLocation)", () => {
    it("handles missing or unsupported navigator.geolocation gracefully", () => {
        withMockEnv({}, ({ dom }) => {
            detectLocation();

            assert.match(
                dom.locationResult.textContent,
                /Geolocation is not supported/
            );
            assert.equal(dom.detectLocation.disabled, false);
        });
    });

    it("shows loading state and passes high-accuracy options to getCurrentPosition", () => {
        let passedOptions = null;
        let callbackExecuted = false;

        withMockEnv({
            geolocation: {
                getCurrentPosition(success, error, options) {
                    passedOptions = options;
                    callbackExecuted = true;
                    success({
                        coords: { latitude: 28.6139, longitude: 77.2090, accuracy: 15 },
                        timestamp: Date.now()
                    });
                }
            }
        }, ({ dom }) => {
            detectLocation();

            assert.equal(callbackExecuted, true);
            assert.deepEqual(passedOptions, {
                enableHighAccuracy: true,
                timeout: 15000,
                maximumAge: 0
            });
            assert.equal(dom.detectLocation.disabled, false);
            assert.match(dom.locationResult.textContent, /Location detected: 28.61390, 77.20900/);
            assert.match(dom.locationResult.textContent, /±15 m/);
        });
    });

    it("handles permission denied error (code 1)", () => {
        withMockEnv({
            geolocation: {
                getCurrentPosition(success, error) {
                    error({ code: 1, message: "User denied Geolocation" });
                }
            }
        }, ({ dom }) => {
            detectLocation();

            assert.match(dom.locationResult.textContent, /permission denied/i);
            assert.match(dom.locationResult.textContent, /settings/i);
            assert.equal(dom.detectLocation.disabled, false);
        });
    });

    it("handles position unavailable error (code 2)", () => {
        withMockEnv({
            geolocation: {
                getCurrentPosition(success, error) {
                    error({ code: 2, message: "Position unavailable" });
                }
            }
        }, ({ dom }) => {
            detectLocation();

            assert.match(dom.locationResult.textContent, /unavailable/i);
            assert.equal(dom.detectLocation.disabled, false);
        });
    });

    it("handles request timeout error (code 3)", () => {
        withMockEnv({
            geolocation: {
                getCurrentPosition(success, error) {
                    error({ code: 3, message: "Timeout" });
                }
            }
        }, ({ dom }) => {
            detectLocation();

            assert.match(dom.locationResult.textContent, /timed out/i);
            assert.equal(dom.detectLocation.disabled, false);
        });
    });

    it("rejects invalid GPS coordinates returned by geolocation callback and clears visuals", () => {
        withMockEnv({
            geolocation: {
                getCurrentPosition(success) {
                    // Out-of-bounds latitude 999
                    success({
                        coords: { latitude: 999, longitude: 50, accuracy: 10 },
                        timestamp: Date.now()
                    });
                }
            }
        }, ({ dom }) => {
            detectLocation();

            assert.match(dom.locationResult.textContent, /Invalid GPS coordinates/i);
        });
    });

    it("displays warning and offers retry when accuracy is poor (> 1000m)", () => {
        withMockEnv({
            geolocation: {
                getCurrentPosition(success) {
                    success({
                        coords: { latitude: 12.9716, longitude: 77.5946, accuracy: 3500 },
                        timestamp: Date.now()
                    });
                }
            }
        }, ({ dom }) => {
            detectLocation();

            assert.match(dom.locationResult.textContent, /Location approximate/i);
            assert.match(dom.locationResult.textContent, /Poor accuracy/i);
            assert.match(dom.locationResult.textContent, /±3500 m/);
        });
    });

    it("prevents duplicate concurrent requests while detection is in-flight", () => {
        let callCount = 0;

        withMockEnv({
            geolocation: {
                getCurrentPosition(success) {
                    callCount++;
                }
            }
        }, ({ dom }) => {
            detectLocation();
            assert.equal(callCount, 1);
            assert.equal(dom.detectLocation.disabled, true);

            // Trigger again while first is pending
            detectLocation();
            assert.equal(callCount, 1); // Still 1, didn't trigger duplicate call
        });
    });
});

describe("Map Coordinate Ordering and Marker/Circle Visuals", () => {
    it("passes [latitude, longitude] in correct order to Leaflet setView, marker, and accuracy circle", () => {
        const testLat = 19.076;
        const testLng = 72.8777;
        const testAccuracy = 35;

        let createdMarker = null;
        let createdCircle = null;
        let mapViewParams = null;

        const mockMapInstance = {
            setView(point, zoom) {
                mapViewParams = { point, zoom };
                return this;
            },
            invalidateSize() {},
            whenReady(cb) { cb(); },
            removeLayer() {}
        };

        global.L = {
            map() {
                return mockMapInstance;
            },
            tileLayer() {
                return { addTo() {}, on() {} };
            },
            marker(point) {
                createdMarker = {
                    point,
                    popup: null,
                    opened: false,
                    setLatLng(pt) { this.point = pt; return this; },
                    bindPopup(txt) { this.popup = txt; return this; },
                    openPopup() { this.opened = true; return this; },
                    addTo() { return this; }
                };
                return createdMarker;
            },
            circle(point, options) {
                createdCircle = {
                    point,
                    radius: options.radius,
                    setLatLng(pt) { this.point = pt; return this; },
                    setRadius(r) { this.radius = r; return this; },
                    addTo() { return this; }
                };
                return createdCircle;
            }
        };

        withMockEnv({}, () => {
            updateUserLocationVisuals(testLat, testLng, testAccuracy);

            assert.ok(mapViewParams);
            assert.deepEqual(mapViewParams.point, [testLat, testLng]);
            assert.equal(mapViewParams.zoom, 17); // for accuracy <= 50

            assert.ok(createdMarker);
            assert.deepEqual(createdMarker.point, [testLat, testLng]);
            assert.match(createdMarker.popup, /19.07600, 72.87770/);
            assert.equal(createdMarker.opened, true);

            assert.ok(createdCircle);
            assert.deepEqual(createdCircle.point, [testLat, testLng]);
            assert.equal(createdCircle.radius, testAccuracy);

            // Test marker updating without recreating
            const newLat = 19.080;
            const newLng = 72.880;
            const newAccuracy = 120;
            updateUserLocationVisuals(newLat, newLng, newAccuracy);

            assert.deepEqual(mapViewParams.point, [newLat, newLng]);
            assert.equal(mapViewParams.zoom, 16); // for accuracy 120m
            assert.deepEqual(createdMarker.point, [newLat, newLng]);
            assert.deepEqual(createdCircle.point, [newLat, newLng]);
            assert.equal(createdCircle.radius, newAccuracy);

            // Clear visuals test
            clearUserLocationVisuals();
        });
    });
});
