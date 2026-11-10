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

  it("names an accepted eject", () => {
    expect(actionNotice({ ok: true, result: { action: "eject", via: "direct" }, epoch: "epoch", revision: 5 })).toBe(
      "UDisks2 accepted eject.",
    );
  });
});
