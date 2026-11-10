import { describe, expect, it } from "vitest";
import { isProvenHardwareCapability } from "./proven";

describe("isProvenHardwareCapability", () => {
  it("does not treat inventory or an unvalidated ready flag as proof", () => {
    expect(isProvenHardwareCapability({ capability: "untested", hardware_validated: false })).toBe(false);
    expect(isProvenHardwareCapability({ capability: "observed", hardware_validated: false })).toBe(false);
    expect(isProvenHardwareCapability({ capability: "ready", hardware_validated: false })).toBe(false);
    expect(isProvenHardwareCapability({ capability: "ready" })).toBe(false);
  });

  it("requires both a ready capability and an explicit host validation flag", () => {
    expect(isProvenHardwareCapability({ capability: "ready", hardware_validated: true })).toBe(true);
  });
});
