import { describe, expect, it } from "vitest";
import { chosenDumpFolder, dumpFolderRequest } from "./dumpRequest";

describe("dump folder picker", () => {
  it("starts in the resolved home and lists folders", () => {
    const request = dumpFolderRequest("/var/home/hostuser");
    expect(request.select).toBe(1);
    expect(request.startPath).toBe("/var/home/hostuser");
    expect(request.includeFolders).toBe(true);
    expect(request.includeFiles).toBe(true);
    expect(request).not.toHaveProperty("max");
  });

  it("uses the resolved folder", () => {
    expect(chosenDumpFolder({ path: "/home/hostuser/dumps", realpath: "/var/home/hostuser/dumps" })).toBe(
      "/var/home/hostuser/dumps",
    );
    expect(chosenDumpFolder({ path: "/var/mnt/dumps/game.iso" })).toBeNull();
  });
});
