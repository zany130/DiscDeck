import { describe, expect, it } from "vitest";
import { chosenIsoPath, isoPickerRequest } from "./isoPicker";

describe("iso picker", () => {
  it("shows folders and does not limit the page to one entry", () => {
    const request = isoPickerRequest("/var/home/hostuser");
    expect(request.includeFolders).toBe(true);
    expect(request.includeFiles).toBe(true);
    expect(request.startPath).toBe("/var/home/hostuser");
    expect(request.extensions).toEqual(["iso"]);
    expect(request.allowAllFiles).toBe(true);
    expect(request).not.toHaveProperty("max");
  });

  it("starts at the filesystem root when home is unknown", () => {
    expect(isoPickerRequest(null).startPath).toBe("/");
    expect(isoPickerRequest("relative").startPath).toBe("/");
  });

  it("uses the resolved path so a home symlink is not mounted", () => {
    expect(chosenIsoPath({ path: "/home/hostuser/game.iso", realpath: "/var/home/hostuser/game.iso" })).toBe(
      "/var/home/hostuser/game.iso",
    );
    expect(chosenIsoPath({ path: "/var/home/hostuser/game.iso" })).toBe("/var/home/hostuser/game.iso");
    expect(chosenIsoPath(null)).toBeNull();
  });
});
