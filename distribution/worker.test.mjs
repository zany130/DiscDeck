import assert from "node:assert/strict";
import test from "node:test";
import { resolveRequest } from "./worker.mjs";

test("development and stable downloads stay on separate pointers", () => {
  assert.deepEqual(resolveRequest("/dev/DiscDeck.zip"), {
    channel: "development",
    kind: "zip",
    pointer: "dev/latest.json",
  });
  assert.equal(resolveRequest("/stable/DiscDeck.zip").pointer, "stable/latest.json");
  assert.equal(resolveRequest("/dev/DiscDeck.zip").channel, "development");
  assert.notEqual(resolveRequest("/dev/DiscDeck.zip").pointer, resolveRequest("/stable/DiscDeck.zip").pointer);
});

test("unknown paths are not treated as a build", () => {
  assert.equal(resolveRequest("/"), null);
  assert.equal(resolveRequest("/dev/private"), null);
});
