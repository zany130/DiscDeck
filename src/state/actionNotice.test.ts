import { describe, expect, it } from "vitest";
import { actionNotice } from "./actionNotice";

describe("actionNotice", () => {
  it("shows the backend refusal instead of a revision counter", () => {
    expect(
      actionNotice({
        ok: false,
        code: "NOT_READY",
        message: "This drive has no mounted-capable media in the current UDisks2 snapshot.",
        retryable: true,
        epoch: "epoch",
        revision: 4,
      }),
    ).toBe("NOT_READY: This drive has no mounted-capable media in the current UDisks2 snapshot.");
  });

  it("names a same-user tray command after UDisks2 denies the process", () => {
    expect(
      actionNotice({ ok: true, result: { action: "eject", via: "user-eject" }, epoch: "epoch", revision: 6 }),
    ).toBe("UDisks2 did not authorize this process. The tray command ran as the current user.");
  });

  it("says a started dump is not verified", () => {
    expect(actionNotice({ ok: true, result: { action: "start_dump", verification: "unverified" }, epoch: "epoch", revision: 8 })).toBe(
      "Redumper started. Progress is indeterminate, and a finished process is not a verified dump.",
    );
  });

  it("says a CDEmu load is not a verified launch", () => {
    expect(
      actionNotice({
        ok: true,
        result: { action: "load_virtual", device_number: 0, sr_device: "/dev/sr4", via: "started" },
        epoch: "epoch",
        revision: 9,
      }),
    ).toBe("Loaded into CDEmu device 0 at /dev/sr4. This is not a verified launch.");
  });

  it("names an accepted eject", () => {
    expect(actionNotice({ ok: true, result: { action: "eject", via: "direct" }, epoch: "epoch", revision: 5 })).toBe(
      "UDisks2 accepted eject.",
    );
  });
});
