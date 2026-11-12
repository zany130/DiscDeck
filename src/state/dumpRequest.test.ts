import { describe, expect, it } from "vitest";
import { chosenDumpFolder, dumpFolderRequest, publishDumpFolder, rememberedDumpFolder, subscribeDumpFolder } from "./dumpRequest";

describe("dump folder picker", () => {
  it("starts in the resolved home and lists folders", () => {
    const request = dumpFolderRequest("/var/home/hostuser");
    expect(request.select).toBe(1);
    expect(request.startPath).toBe("/var/home/hostuser");
    expect(request.includeFolders).toBe(true);
    expect(request.includeFiles).toBe(false);
    expect(request).not.toHaveProperty("max");
  });

  it("uses the resolved folder", () => {
    expect(chosenDumpFolder({ path: "/home/hostuser/dumps", realpath: "/var/home/hostuser/dumps" })).toBe(
      "/var/home/hostuser/dumps",
    );
    expect(chosenDumpFolder({ path: "/var/mnt/dumps/", realpath: "file:///var/mnt/dumps/" })).toBe("/var/mnt/dumps");
    expect(chosenDumpFolder({ path: "/var/mnt/dumps/game.iso" })).toBeNull();
  });
});

describe("dump folder memory", () => {
  it("keeps the folder for a page that mounts after the picker closes", () => {
    publishDumpFolder(null);
    const seen: Array<string | null> = [];
    const stop = subscribeDumpFolder((folder) => seen.push(folder));
    publishDumpFolder("/var/home/hostuser/dumps");
    stop();
    expect(seen).toEqual([null, "/var/home/hostuser/dumps"]);
    expect(rememberedDumpFolder()).toBe("/var/home/hostuser/dumps");
    publishDumpFolder(null);
  });
});
