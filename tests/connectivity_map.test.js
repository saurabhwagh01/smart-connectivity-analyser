/**
 * Tests for Connectivity Map Fallback and Location Handling
 *
 * Verifies that:
 * 1. Geolocation errors (denied permission, unavailable, timeout) produce clear, user-friendly messages.
 * 2. Precise location coordinates are truncated for privacy, avoiding unnecessary exposure.
 * 3. Map initialization failures (missing Leaflet, errors) are handled gracefully with a fallback UI.
 * 4. The retry option is provided and functions properly.
 * 5. Dashboard features remain intact when map/location services are unavailable.
 */

const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert');
const {
    formatCoordinatePrivacy,
    getLocationErrorMessage,
    showMapFallback,
    initializeMap,
    smartConnectivity
} = require('../js/script.js');

describe('Connectivity Map & Location Resilience Test Suite', () => {

    /* =========================================================
       1. Location Error Messages (Graceful Handling)
       ========================================================= */
    describe('getLocationErrorMessage()', () => {

        it('handles PERMISSION_DENIED (code 1) gracefully without browser-specific wording', () => {
            const error = { code: 1, message: 'User denied Geolocation' };
            const message = getLocationErrorMessage(error);

            assert.strictEqual(typeof message, 'string');
            assert.match(message, /denied/i);
            assert.match(message, /permission/i);
            // Verify it does not mention specific browsers like Chrome, maintaining cross-browser neutrality
            assert.doesNotMatch(message, /chrome/i);
            assert.doesNotMatch(message, /firefox/i);
        });

        it('handles POSITION_UNAVAILABLE (code 2) gracefully', () => {
            const error = { code: 2, message: 'Position unavailable' };
            const message = getLocationErrorMessage(error);

            assert.strictEqual(typeof message, 'string');
            assert.match(message, /unavailable/i);
            assert.match(message, /location/i);
        });

        it('handles TIMEOUT (code 3) gracefully', () => {
            const error = { code: 3, message: 'Timeout expired' };
            const message = getLocationErrorMessage(error);

            assert.strictEqual(typeof message, 'string');
            assert.match(message, /timed out/i);
        });

        it('handles unknown error codes with a clear generic fallback message', () => {
            const unknownError = { code: 99, message: 'Unknown error' };
            const message = getLocationErrorMessage(unknownError);

            assert.strictEqual(typeof message, 'string');
            assert.match(message, /unable to determine/i);
        });

        it('handles null or undefined error objects safely', () => {
            const nullMsg = getLocationErrorMessage(null);
            const undefMsg = getLocationErrorMessage(undefined);

            assert.strictEqual(typeof nullMsg, 'string');
            assert.strictEqual(typeof undefMsg, 'string');
            assert.match(nullMsg, /unable/i);
            assert.match(undefMsg, /unable/i);
        });
    });

    /* =========================================================
       2. Privacy-Conscious Coordinate Formatting
       ========================================================= */
    describe('formatCoordinatePrivacy()', () => {

        it('truncates 6-decimal high-precision coordinates to 2 decimal places', () => {
            // Raw GPS coordinates typically have 6 decimal places (~10cm precision)
            const rawLat = 18.520432;
            const rawLon = 73.856743;

            const privacyDisplay = formatCoordinatePrivacy(rawLat, rawLon);

            // 2 decimal places represents ~1.1 km area, protecting exact personal location
            assert.strictEqual(privacyDisplay, '18.52°, 73.86°');
            assert.doesNotMatch(privacyDisplay, /18\.520432/);
            assert.doesNotMatch(privacyDisplay, /73\.856743/);
        });

        it('supports custom precision while remaining privacy-aware', () => {
            const formatted = formatCoordinatePrivacy(40.712776, -74.005974, 3);
            assert.strictEqual(formatted, '40.713°, -74.006°');
        });

        it('handles string coordinates properly', () => {
            const formatted = formatCoordinatePrivacy('51.5074', '-0.1278');
            assert.strictEqual(formatted, '51.51°, -0.13°');
        });

        it('returns "Unavailable" for null or undefined coordinates', () => {
            assert.strictEqual(formatCoordinatePrivacy(null, null), 'Unavailable');
            assert.strictEqual(formatCoordinatePrivacy(18.52, null), 'Unavailable');
            assert.strictEqual(formatCoordinatePrivacy(null, 73.85), 'Unavailable');
            assert.strictEqual(formatCoordinatePrivacy(undefined, undefined), 'Unavailable');
        });

        it('returns "Unavailable" for NaN or non-finite inputs', () => {
            assert.strictEqual(formatCoordinatePrivacy(NaN, 73.85), 'Unavailable');
            assert.strictEqual(formatCoordinatePrivacy(18.52, Infinity), 'Unavailable');
            assert.strictEqual(formatCoordinatePrivacy('invalid', 'coords'), 'Unavailable');
            assert.strictEqual(formatCoordinatePrivacy('', ''), 'Unavailable');
        });
    });

    /* =========================================================
       3. Map Fallback UI & Fault Tolerance
       ========================================================= */
    describe('Map Fallback & Error Handling', () => {

        it('initializeMap does not throw an exception when Leaflet (L) is undefined', () => {
            // In Node.js environment, L is undefined by default
            assert.doesNotThrow(() => {
                initializeMap();
            });
        });

        it('showMapFallback renders title, message, and retry button when container is present', () => {
            let innerHtmlContent = '';
            const mockContainer = {
                set innerHTML(html) {
                    innerHtmlContent = html;
                },
                get innerHTML() {
                    return innerHtmlContent;
                }
            };

            // Temporarily mock document.getElementById for connectivityMap
            const origGetElement = global.document && global.document.getElementById;
            global.document = global.document || {};
            global.document.getElementById = (id) => {
                if (id === 'connectivityMap') return mockContainer;
                return null;
            };

            showMapFallback('Map Service Unavailable', 'Unable to load tiles.', true);

            assert.match(innerHtmlContent, /Map Service Unavailable/);
            assert.match(innerHtmlContent, /Unable to load tiles\./);
            assert.match(innerHtmlContent, /retryMapLoad/);
            assert.match(innerHtmlContent, /Retry Loading Map/);

            // Restore
            if (origGetElement) {
                global.document.getElementById = origGetElement;
            } else {
                delete global.document;
            }
        });

        it('showMapFallback omits retry button when canRetry is false', () => {
            let innerHtmlContent = '';
            const mockContainer = {
                set innerHTML(html) {
                    innerHtmlContent = html;
                },
                get innerHTML() {
                    return innerHtmlContent;
                }
            };

            global.document = global.document || {};
            global.document.getElementById = (id) => {
                if (id === 'connectivityMap') return mockContainer;
                return null;
            };

            showMapFallback('Offline Notice', 'No map available.', false);

            assert.match(innerHtmlContent, /Offline Notice/);
            assert.doesNotMatch(innerHtmlContent, /retryMapLoad/);

            delete global.document;
        });

        it('initializeMap handles missing map element gracefully without throwing', () => {
            global.document = {
                getElementById: () => null
            };

            assert.doesNotThrow(() => {
                initializeMap();
            });

            delete global.document;
        });
    });

    /* =========================================================
       4. smartConnectivity Export Verification
       ========================================================= */
    describe('smartConnectivity Map Exports', () => {

        it('exports map and location helper functions', () => {
            assert.strictEqual(typeof smartConnectivity.formatCoordinatePrivacy, 'function');
            assert.strictEqual(typeof smartConnectivity.getLocationErrorMessage, 'function');
            assert.strictEqual(typeof smartConnectivity.showMapFallback, 'function');
            assert.strictEqual(typeof smartConnectivity.initializeMap, 'function');
            assert.strictEqual(typeof smartConnectivity.detectCurrentLocation, 'function');
            assert.strictEqual(typeof smartConnectivity.saveCurrentLocation, 'function');
            assert.strictEqual(typeof smartConnectivity.findBetterConnectionArea, 'function');
        });
    });
});

