const { describe, test } = require("node:test");
const assert = require("node:assert/strict");

const {
    normalizeNetworkInterfaces,
    resolveNetworkInterfaceSelection,
    buildNetworkQualityUrl
} = require("../js/script.js");

const DISCOVERED = {
    supported: true,
    selected: "auto",
    interfaces: [
        { id: "auto", name: "Automatic (System default)", status: "active", is_default: true },
        { id: "en0", name: "Wi-Fi", status: "connected", is_default: false },
        { id: "en5", name: "USB Ethernet", status: "disconnected", is_default: false }
    ]
};

describe("Network interface discovery response", () => {
    test("keeps automatic mode and discovered names/status only", () => {
        const interfaces = normalizeNetworkInterfaces(DISCOVERED);

        assert.deepEqual(interfaces, DISCOVERED.interfaces);
        assert.equal(interfaces.some((item) => "address" in item || "mac" in item), false);
    });

    test("returns no selectable list when discovery is unsupported", () => {
        assert.deepEqual(normalizeNetworkInterfaces({
            supported: false,
            selected: "auto",
            interfaces: [{ id: "auto", name: "Automatic", status: "active" }]
        }), []);
    });

    test("ignores malformed interface records", () => {
        const interfaces = normalizeNetworkInterfaces({
            supported: true,
            interfaces: [
                { id: "auto", name: "Automatic", status: "active" },
                { id: "bad", name: "Broken", status: "unknown" },
                { id: 42, name: "Invalid id", status: "connected" },
                null
            ]
        });

        assert.deepEqual(interfaces.map((item) => item.id), ["auto"]);
    });
});

describe("Interface selection validation", () => {
    test("automatic is always a valid default", () => {
        assert.deepEqual(
            resolveNetworkInterfaceSelection("auto", DISCOVERED.interfaces),
            { ok: true, value: "auto" }
        );
        assert.deepEqual(
            resolveNetworkInterfaceSelection("", DISCOVERED.interfaces),
            { ok: true, value: "auto" }
        );
    });

    test("accepts a currently connected adapter", () => {
        assert.deepEqual(
            resolveNetworkInterfaceSelection("en0", DISCOVERED.interfaces),
            { ok: true, value: "en0" }
        );
    });

    test("rejects a disconnected adapter with a clear message", () => {
        const result = resolveNetworkInterfaceSelection("en5", DISCOVERED.interfaces);

        assert.equal(result.ok, false);
        assert.match(result.message, /disconnected/i);
        assert.match(result.message, /Automatic/);
    });

    test("rejects an interface removed since discovery", () => {
        const afterRemoval = DISCOVERED.interfaces.filter((item) => item.id !== "en0");
        const result = resolveNetworkInterfaceSelection("en0", afterRemoval);

        assert.equal(result.ok, false);
        assert.match(result.message, /no longer available/i);
        assert.match(result.message, /Automatic/);
    });
});

describe("Network quality request URL", () => {
    test("keeps the existing automatic request unchanged", () => {
        assert.equal(
            buildNetworkQualityUrl("http://127.0.0.1:8000/api/", null, "auto"),
            "http://127.0.0.1:8000/api/network-quality"
        );
    });

    test("sends profile and selected adapter together", () => {
        const url = buildNetworkQualityUrl(
            "http://127.0.0.1:8000/api",
            "quick check",
            "en0"
        );

        const parsed = new URL(url);
        assert.equal(parsed.pathname, "/api/network-quality");
        assert.equal(parsed.searchParams.get("profile"), "quick check");
        assert.equal(parsed.searchParams.get("interface"), "en0");
    });

    test("omits automatic mode from the query string", () => {
        const parsed = new URL(buildNetworkQualityUrl(
            "http://127.0.0.1:8000/api",
            "quick",
            "auto"
        ));

        assert.equal(parsed.searchParams.get("profile"), "quick");
        assert.equal(parsed.searchParams.has("interface"), false);
    });
});
