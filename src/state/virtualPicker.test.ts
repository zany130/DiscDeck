import { describe, expect, it } from "vitest";
import { chosenDiscPath, virtualPickerRequest } from "./virtualPicker";

describe("virtual disc picker", () => {
  it("offers cue sheets and iso files without limiting the page", () => {
    const request = virtualPickerRequest("/var/home/hostuser");
    expect(request.includeFolders).toBe(true);
    expect(request.includeFiles).toBe(true);
    expect(request.startPath).toBe("/var/home/hostuser");
    expect(request.extensions).toEqual(["cue", "iso"]);
    expect(request.allowAllFiles).toBe(true);
    expect(request).not.toHaveProperty("max");
  });

  it("uses the resolved path", () => {
    expect(chosenDiscPath({ path: "/home/hostuser/game.cue", realpath: "/var/home/hostuser/game.cue" })).toBe(
      "/var/home/hostuser/game.cue",
    );
    expect(chosenDiscPath(null)).toBeNull();
  });
});