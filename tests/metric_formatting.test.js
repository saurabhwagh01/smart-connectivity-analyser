/**
 * Tests for Network Metric Formatting
 * 
 * Verifies that:
 * 1. Valid metric values (download, upload, ping, jitter, packet loss) are formatted correctly.
 * 2. Missing or unavailable values (null, undefined, NaN, empty strings, invalid inputs)
 *    are handled consistently across all metrics.
 * 3. Valid zero values (e.g. 0% packet loss, 0 Mbps, 0 ms) are displayed correctly.
 * 4. Unavailable values are NEVER incorrectly displayed as zero.
 */

const { describe, it } = require('node:test');
const assert = require('node:assert');
const {
    formatNumber,
    formatMetric,
    formatNetworkMetric,
    isValidMetricNumber,
    METRIC_UNITS
} = require('../js/script.js');

describe('Network Metric Formatting Test Suite', () => {

    /* =========================================================
       1. formatNumber
       ========================================================= */
    describe('formatNumber()', () => {

        describe('Valid metric values', () => {
            it('formats positive float numbers with default 1 decimal place', () => {
                assert.strictEqual(formatNumber(12.345), '12.3');
                assert.strictEqual(formatNumber(100.89), '100.9');
                assert.strictEqual(formatNumber(45), '45.0');
            });

            it('formats numbers with custom decimal places', () => {
                assert.strictEqual(formatNumber(12.3456, 2), '12.35');
                assert.strictEqual(formatNumber(12.3456, 3), '12.346');
                assert.strictEqual(formatNumber(12.3456, 0), '12');
            });

            it('formats numeric string inputs properly', () => {
                assert.strictEqual(formatNumber('25.4'), '25.4');
                assert.strictEqual(formatNumber('100'), '100.0');
            });
        });

        describe('Valid zero values', () => {
            it('formats numeric 0 correctly as "0.0"', () => {
                assert.strictEqual(formatNumber(0), '0.0');
                assert.strictEqual(formatNumber(0.0), '0.0');
            });

            it('formats string "0" correctly as "0.0"', () => {
                assert.strictEqual(formatNumber('0'), '0.0');
                assert.strictEqual(formatNumber('0.0'), '0.0');
            });

            it('formats zero with custom decimal places', () => {
                assert.strictEqual(formatNumber(0, 2), '0.00');
                assert.strictEqual(formatNumber(0, 0), '0');
            });
        });

        describe('Missing or unavailable values', () => {
            it('returns "--" for null', () => {
                assert.strictEqual(formatNumber(null), '--');
            });

            it('returns "--" for undefined', () => {
                assert.strictEqual(formatNumber(undefined), '--');
            });

            it('returns "--" for NaN', () => {
                assert.strictEqual(formatNumber(NaN), '--');
            });

            it('returns "--" for empty string and whitespace', () => {
                assert.strictEqual(formatNumber(''), '--');
                assert.strictEqual(formatNumber('   '), '--');
            });

            it('returns "--" for non-numeric strings', () => {
                assert.strictEqual(formatNumber('Unavailable'), '--');
                assert.strictEqual(formatNumber('N/A'), '--');
                assert.strictEqual(formatNumber('null'), '--');
                assert.strictEqual(formatNumber('undefined'), '--');
            });

            it('returns "--" for non-finite values (Infinity, -Infinity)', () => {
                assert.strictEqual(formatNumber(Infinity), '--');
                assert.strictEqual(formatNumber(-Infinity), '--');
            });

            it('returns "--" for booleans and objects', () => {
                assert.strictEqual(formatNumber(false), '--');
                assert.strictEqual(formatNumber(true), '--');
                assert.strictEqual(formatNumber([]), '--');
                assert.strictEqual(formatNumber({}), '--');
            });
        });

        describe('Verify unavailable values are not incorrectly displayed as zero', () => {
            it('never formats null or undefined as zero', () => {
                assert.notStrictEqual(formatNumber(null), '0.0');
                assert.notStrictEqual(formatNumber(null), '0');
                assert.notStrictEqual(formatNumber(undefined), '0.0');
                assert.notStrictEqual(formatNumber(undefined), '0');
            });

            it('never formats empty string, whitespace or boolean as zero', () => {
                assert.notStrictEqual(formatNumber(''), '0.0');
                assert.notStrictEqual(formatNumber('   '), '0.0');
                assert.notStrictEqual(formatNumber(false), '0.0');
                assert.notStrictEqual(formatNumber([]), '0.0');
            });

            it('never formats NaN as zero', () => {
                assert.notStrictEqual(formatNumber(NaN), '0.0');
            });
        });
    });

    /* =========================================================
       2. formatMetric
       ========================================================= */
    describe('formatMetric()', () => {

        describe('Valid metric values', () => {
            it('formats valid value with unit and 1 decimal place', () => {
                assert.strictEqual(formatMetric(25.4, 'Mbps'), '25.4 Mbps');
                assert.strictEqual(formatMetric(18.2, 'ms'), '18.2 ms');
                assert.strictEqual(formatMetric(2.5, '%'), '2.5 %');
            });

            it('formats valid value without unit', () => {
                assert.strictEqual(formatMetric(50.2), '50.2');
            });

            it('respects custom decimal parameter', () => {
                assert.strictEqual(formatMetric(10.556, 'Mbps', 2), '10.56 Mbps');
                assert.strictEqual(formatMetric(10.556, 'ms', 0), '11 ms');
            });

            it('formats numeric strings with units', () => {
                assert.strictEqual(formatMetric('100.5', 'Mbps'), '100.5 Mbps');
            });
        });

        describe('Valid zero values', () => {
            it('formats valid zero values with unit correctly', () => {
                assert.strictEqual(formatMetric(0, 'Mbps'), '0.0 Mbps');
                assert.strictEqual(formatMetric(0, 'ms'), '0.0 ms');
                assert.strictEqual(formatMetric(0, '%'), '0.0 %');
                assert.strictEqual(formatMetric('0', 'Mbps'), '0.0 Mbps');
            });

            it('formats zero without unit as "0.0"', () => {
                assert.strictEqual(formatMetric(0), '0.0');
            });
        });

        describe('Missing or unavailable values', () => {
            it('returns "Unavailable" for null and undefined', () => {
                assert.strictEqual(formatMetric(null, 'Mbps'), 'Unavailable');
                assert.strictEqual(formatMetric(undefined, 'ms'), 'Unavailable');
            });

            it('returns "Unavailable" for empty string and whitespace', () => {
                assert.strictEqual(formatMetric('', 'Mbps'), 'Unavailable');
                assert.strictEqual(formatMetric('   ', 'ms'), 'Unavailable');
            });

            it('returns "Unavailable" for NaN and non-numeric strings', () => {
                assert.strictEqual(formatMetric(NaN, '%'), 'Unavailable');
                assert.strictEqual(formatMetric('invalid', 'Mbps'), 'Unavailable');
                assert.strictEqual(formatMetric('Unavailable', 'Mbps'), 'Unavailable');
            });

            it('returns "Unavailable" for booleans and non-primitives', () => {
                assert.strictEqual(formatMetric(false, 'Mbps'), 'Unavailable');
                assert.strictEqual(formatMetric(true, 'ms'), 'Unavailable');
                assert.strictEqual(formatMetric([], '%'), 'Unavailable');
                assert.strictEqual(formatMetric({}, 'Mbps'), 'Unavailable');
            });

            it('returns "Unavailable" for non-finite values', () => {
                assert.strictEqual(formatMetric(Infinity, 'ms'), 'Unavailable');
                assert.strictEqual(formatMetric(-Infinity, 'ms'), 'Unavailable');
            });
        });

        describe('Verify unavailable values are not incorrectly displayed as zero', () => {
            it('confirms missing values are not zero with unit', () => {
                assert.notStrictEqual(formatMetric(null, 'Mbps'), '0.0 Mbps');
                assert.notStrictEqual(formatMetric(null, 'Mbps'), '0 Mbps');
                assert.notStrictEqual(formatMetric(undefined, 'ms'), '0.0 ms');
                assert.notStrictEqual(formatMetric(undefined, 'ms'), '0 ms');
                assert.notStrictEqual(formatMetric(null, '%'), '0.0 %');
                assert.notStrictEqual(formatMetric(null, '%'), '0%');
            });

            it('confirms empty strings and falsy non-zeros are not formatted as zero', () => {
                assert.notStrictEqual(formatMetric('', 'Mbps'), '0.0 Mbps');
                assert.notStrictEqual(formatMetric('   ', 'ms'), '0.0 ms');
                assert.notStrictEqual(formatMetric(false, '%'), '0.0 %');
                assert.notStrictEqual(formatMetric(NaN, 'Mbps'), '0.0 Mbps');
            });
        });
    });

    /* =========================================================
       3. formatNetworkMetric (Specific Dashboard Network Metrics)
       ========================================================= */
    describe('formatNetworkMetric()', () => {

        describe('Valid metric values for all supported network metrics', () => {
            it('formats download speed correctly in Mbps', () => {
                assert.strictEqual(formatNetworkMetric('download', 85.4), '85.4 Mbps');
                assert.strictEqual(formatNetworkMetric('download_mbps', 120), '120.0 Mbps');
            });

            it('formats upload speed correctly in Mbps', () => {
                assert.strictEqual(formatNetworkMetric('upload', 42.1), '42.1 Mbps');
                assert.strictEqual(formatNetworkMetric('upload_mbps', 35), '35.0 Mbps');
            });

            it('formats ping latency correctly in ms', () => {
                assert.strictEqual(formatNetworkMetric('ping', 18.6), '18.6 ms');
                assert.strictEqual(formatNetworkMetric('ping_ms', 24), '24.0 ms');
            });

            it('formats jitter correctly in ms', () => {
                assert.strictEqual(formatNetworkMetric('jitter', 3.2), '3.2 ms');
                assert.strictEqual(formatNetworkMetric('jitter_ms', 1.5), '1.5 ms');
            });

            it('formats packet loss correctly in %', () => {
                assert.strictEqual(formatNetworkMetric('packetLoss', 2.0), '2.0 %');
                assert.strictEqual(formatNetworkMetric('packet_loss', 0.5), '0.5 %');
            });
        });

        describe('Valid zero values for all supported network metrics', () => {
            it('correctly displays valid 0.0 Mbps download speed', () => {
                assert.strictEqual(formatNetworkMetric('download', 0), '0.0 Mbps');
                assert.strictEqual(formatNetworkMetric('download_mbps', '0'), '0.0 Mbps');
            });

            it('correctly displays valid 0.0 Mbps upload speed', () => {
                assert.strictEqual(formatNetworkMetric('upload', 0), '0.0 Mbps');
                assert.strictEqual(formatNetworkMetric('upload_mbps', '0'), '0.0 Mbps');
            });

            it('correctly displays valid 0.0 ms ping latency', () => {
                assert.strictEqual(formatNetworkMetric('ping', 0), '0.0 ms');
                assert.strictEqual(formatNetworkMetric('ping_ms', '0'), '0.0 ms');
            });

            it('correctly displays valid 0.0 ms jitter', () => {
                assert.strictEqual(formatNetworkMetric('jitter', 0), '0.0 ms');
                assert.strictEqual(formatNetworkMetric('jitter_ms', '0'), '0.0 ms');
            });

            it('correctly displays valid 0.0 % packet loss (ideal connection)', () => {
                // A zero packet loss is a valid, highly desirable network measurement
                assert.strictEqual(formatNetworkMetric('packetLoss', 0), '0.0 %');
                assert.strictEqual(formatNetworkMetric('packet_loss', 0), '0.0 %');
                assert.strictEqual(formatNetworkMetric('packetLoss', '0.0'), '0.0 %');
            });
        });

        describe('Missing or unavailable metric values', () => {
            it('consistently returns "Unavailable" for null across all metrics', () => {
                assert.strictEqual(formatNetworkMetric('download', null), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('upload', null), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('ping', null), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('jitter', null), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('packetLoss', null), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('packet_loss', null), 'Unavailable');
            });

            it('consistently returns "Unavailable" for undefined across all metrics', () => {
                assert.strictEqual(formatNetworkMetric('download', undefined), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('upload', undefined), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('ping', undefined), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('jitter', undefined), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('packetLoss', undefined), 'Unavailable');
            });

            it('consistently returns "Unavailable" for NaN across all metrics', () => {
                assert.strictEqual(formatNetworkMetric('download', NaN), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('upload', NaN), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('ping', NaN), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('jitter', NaN), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('packetLoss', NaN), 'Unavailable');
            });

            it('consistently returns "Unavailable" for empty strings across all metrics', () => {
                assert.strictEqual(formatNetworkMetric('download', ''), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('upload', '   '), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('ping', ''), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('jitter', ''), 'Unavailable');
                assert.strictEqual(formatNetworkMetric('packetLoss', ''), 'Unavailable');
            });
        });

        describe('Verify unavailable values are not incorrectly displayed as zero', () => {
            it('ensures unavailable packet loss is NOT displayed as 0.0 %', () => {
                // Critical requirement: unavailable packet loss must not look like 0% loss (perfect health)
                const nullLoss = formatNetworkMetric('packetLoss', null);
                assert.notStrictEqual(nullLoss, '0.0 %');
                assert.notStrictEqual(nullLoss, '0%');
                assert.strictEqual(nullLoss, 'Unavailable');

                const undefLoss = formatNetworkMetric('packetLoss', undefined);
                assert.notStrictEqual(undefLoss, '0.0 %');
                assert.strictEqual(undefLoss, 'Unavailable');

                const nanLoss = formatNetworkMetric('packetLoss', NaN);
                assert.notStrictEqual(nanLoss, '0.0 %');
                assert.strictEqual(nanLoss, 'Unavailable');

                const emptyLoss = formatNetworkMetric('packetLoss', '');
                assert.notStrictEqual(emptyLoss, '0.0 %');
                assert.strictEqual(emptyLoss, 'Unavailable');
            });

            it('ensures unavailable ping is NOT displayed as 0.0 ms', () => {
                const nullPing = formatNetworkMetric('ping', null);
                assert.notStrictEqual(nullPing, '0.0 ms');
                assert.notStrictEqual(nullPing, '0 ms');
                assert.strictEqual(nullPing, 'Unavailable');
            });

            it('ensures unavailable jitter is NOT displayed as 0.0 ms', () => {
                const nullJitter = formatNetworkMetric('jitter', null);
                assert.notStrictEqual(nullJitter, '0.0 ms');
                assert.notStrictEqual(nullJitter, '0 ms');
                assert.strictEqual(nullJitter, 'Unavailable');
            });

            it('ensures unavailable download speed is NOT displayed as 0.0 Mbps', () => {
                const nullDownload = formatNetworkMetric('download', null);
                assert.notStrictEqual(nullDownload, '0.0 Mbps');
                assert.notStrictEqual(nullDownload, '0 Mbps');
                assert.strictEqual(nullDownload, 'Unavailable');
            });

            it('ensures unavailable upload speed is NOT displayed as 0.0 Mbps', () => {
                const nullUpload = formatNetworkMetric('upload', null);
                assert.notStrictEqual(nullUpload, '0.0 Mbps');
                assert.notStrictEqual(nullUpload, '0 Mbps');
                assert.strictEqual(nullUpload, 'Unavailable');
            });
        });
    });

    /* =========================================================
       4. Real-world API & Dashboard Flow Verification
       ========================================================= */
    describe('Dashboard & API Response Simulation', () => {

        it('handles complete backend network quality response', () => {
            const apiData = {
                target: '1.1.1.1',
                packets_sent: 10,
                packets_received: 10,
                packet_loss: 0.0,
                ping_ms: 14.5,
                jitter_ms: 1.8,
                status: 'excellent'
            };

            const pingText = formatNetworkMetric('ping', apiData.ping_ms);
            const jitterText = formatNetworkMetric('jitter', apiData.jitter_ms);
            const packetLossText = formatNetworkMetric('packetLoss', apiData.packet_loss);

            assert.strictEqual(pingText, '14.5 ms');
            assert.strictEqual(jitterText, '1.8 ms');
            assert.strictEqual(packetLossText, '0.0 %');
        });

        it('handles unreachable/offline backend network quality response', () => {
            const unreachableData = {
                target: '1.1.1.1',
                packets_sent: 10,
                packets_received: 0,
                packet_loss: 100.0,
                ping_ms: null,
                jitter_ms: null,
                status: 'unreachable'
            };

            const pingText = formatNetworkMetric('ping', unreachableData.ping_ms);
            const jitterText = formatNetworkMetric('jitter', unreachableData.jitter_ms);
            const packetLossText = formatNetworkMetric('packetLoss', unreachableData.packet_loss);

            assert.strictEqual(pingText, 'Unavailable');
            assert.strictEqual(jitterText, 'Unavailable');
            assert.strictEqual(packetLossText, '100.0 %');

            // Ping and jitter must not default to 0
            assert.notStrictEqual(pingText, '0.0 ms');
            assert.notStrictEqual(jitterText, '0.0 ms');
        });

        it('handles backend response with missing or corrupt packet loss', () => {
            const corruptData = {
                ping_ms: 22.4,
                jitter_ms: 3.1,
                packet_loss: null
            };

            const lossText = formatNetworkMetric('packetLoss', corruptData.packet_loss);
            assert.strictEqual(lossText, 'Unavailable');
            assert.notStrictEqual(lossText, '0.0 %');
        });

        it('handles Cloudflare speed test bandwidth conversion and formatting', () => {
            // Cloudflare returns bandwidth in bps
            const downloadBandwidthBps = 75400000;
            const downloadMbps = downloadBandwidthBps / 1000000;
            assert.strictEqual(formatNetworkMetric('download', downloadMbps), '75.4 Mbps');

            const zeroBandwidthBps = 0;
            const zeroMbps = zeroBandwidthBps / 1000000;
            assert.strictEqual(formatNetworkMetric('download', zeroMbps), '0.0 Mbps');

            const unavailableBandwidth = null;
            assert.strictEqual(formatNetworkMetric('download', unavailableBandwidth), 'Unavailable');
        });
    });
    /* =========================================================
       5. isValidMetricNumber & Non-nested Formatting Verification
       ========================================================= */
    describe('isValidMetricNumber()', () => {
        it('returns true for valid finite numbers and valid zero', () => {
            assert.strictEqual(isValidMetricNumber(50.5), true);
            assert.strictEqual(isValidMetricNumber(0), true);
            assert.strictEqual(isValidMetricNumber(0.0), true);
            assert.strictEqual(isValidMetricNumber('0'), true);
            assert.strictEqual(isValidMetricNumber('12.5'), true);
        });

        it('returns false for null, undefined, empty strings, and booleans', () => {
            assert.strictEqual(isValidMetricNumber(null), false);
            assert.strictEqual(isValidMetricNumber(undefined), false);
            assert.strictEqual(isValidMetricNumber(''), false);
            assert.strictEqual(isValidMetricNumber('   '), false);
            assert.strictEqual(isValidMetricNumber(false), false);
            assert.strictEqual(isValidMetricNumber(true), false);
        });

        it('returns false for NaN, Infinity, objects, and non-numeric strings', () => {
            assert.strictEqual(isValidMetricNumber(NaN), false);
            assert.strictEqual(isValidMetricNumber(Infinity), false);
            assert.strictEqual(isValidMetricNumber(-Infinity), false);
            assert.strictEqual(isValidMetricNumber({}), false);
            assert.strictEqual(isValidMetricNumber([]), false);
            assert.strictEqual(isValidMetricNumber('Unavailable'), false);
            assert.strictEqual(isValidMetricNumber('abc'), false);
        });
    });

    describe('Avoiding Nested Formatting & Double Units', () => {
        it('ensures formatNetworkMetric directly formats session metrics without manual unit appending', () => {
            const avgSpeed = 45.2;
            const formattedDirectly = formatNetworkMetric('download', avgSpeed);
            assert.strictEqual(formattedDirectly, '45.2 Mbps');

            // Must not double append unit
            assert.doesNotMatch(formattedDirectly, /Mbps.*Mbps/);

            // Output of formatNetworkMetric should not be passed to formatNumber
            const pingFormatted = formatNetworkMetric('ping', 15.0);
            assert.strictEqual(pingFormatted, '15.0 ms');
            assert.doesNotMatch(pingFormatted, /ms.*ms/);
        });

        it('ensures zero session values do not double append units', () => {
            const zeroSpeed = formatNetworkMetric('download', 0);
            assert.strictEqual(zeroSpeed, '0.0 Mbps');
            assert.doesNotMatch(zeroSpeed, /Mbps.*Mbps/);

            const zeroPing = formatNetworkMetric('ping', 0);
            assert.strictEqual(zeroPing, '0.0 ms');
            assert.doesNotMatch(zeroPing, /ms.*ms/);
        });
    });
});