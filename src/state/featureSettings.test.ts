import { describe, expect, it } from "vitest";
import { defaultFeatureSettings, effectiveState } from "./featureSettings";

describe("feature settings", () => {
  it("keeps experimental launch and autoplay off", () => {
    const settings = defaultFeatureSettings();
    expect(settings.modules["launch.experimental"]).toBe(false);
    expect(settings.modules["launch.autoplay"]).toBe(false);
  });

  it("does not treat an untested module as active", () => {
    expect(effectiveState(true, "untested", false)).toBe("unavailable");
    expect(effectiveState(false, "untested", false)).toBe("disabled");
    expect(effectiveState(false, "ready", true)).toBe("disable_pending");
  });
});
