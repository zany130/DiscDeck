import { describe, expect, it } from "vitest";
import { dumpOffer } from "./dumpOffer";

describe("dump offer", () => {
  it("keeps a dump control visible when no optical drive is listed", () => {
    expect(dumpOffer(null, "/var/home/hostuser/dumps")).toEqual({
      label: "Dump",
      enabled: false,
      reason: "No optical drive is visible.",
    });
  });

  it("asks for a folder before the button can start", () => {
    expect(dumpOffer({ block_node: "/dev/sr0", media_present: true }, null)).toEqual({
      label: "Dump /dev/sr0",
      enabled: false,
      reason: "Choose a dump folder first.",
    });
  });

  it("stays disabled until media is present", () => {
    expect(dumpOffer({ block_node: "/dev/sr0", media_present: false }, "/dumps").enabled).toBe(false);
    expect(dumpOffer({ block_node: "/dev/sr0", media_present: "unknown" }, "/dumps").reason).toBe(
      "Media presence is unknown. Refresh diagnostics.",
    );
  });

  it("enables the named drive once a folder and media are ready", () => {
    expect(dumpOffer({ block_node: "/dev/sr1", media_present: true }, "/dumps")).toEqual({
      label: "Dump /dev/sr1",
      enabled: true,
      reason: null,
    });
  });
});
