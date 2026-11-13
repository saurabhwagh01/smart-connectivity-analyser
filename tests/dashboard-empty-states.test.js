const test = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");

// Run the dashboard in a real Chromium browser and assert the four user-visible
// states. The shared scenario runner also captures screenshots for the PR.
test("dashboard empty, API error, populated history, and AI fallback behave correctly", () => {
  const runner = path.join(__dirname, "issue-5-browser-demo.cjs");
  const result = spawnSync(process.execPath, [runner], {
    cwd: process.cwd(),
    encoding: "utf8",
    timeout: 120000
  });

  assert.equal(
    result.status,
    0,
    [result.stdout, result.stderr].filter(Boolean).join("\n") ||
      "Browser behavior scenarios failed."
  );
  assert.match(result.stdout, /All four Issue #5 browser scenarios passed/);
});
