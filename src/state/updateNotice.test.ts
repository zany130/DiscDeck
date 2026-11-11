import { describe, expect, it } from "vitest";
import { updateNotice, versionLabel } from "./updateNotice";

describe("update notice", () => {
  it("names the running version when the published commit matches", () => {
    expect(updateNotice({ up_to_date: true, current_version: "0.2.0" })).toEqual({
      message: "Version 0.2.0 is the latest development build.",
      offer: null,
    });
  });

  it("offers the published version when the commit differs", () => {
    const notice = updateNotice({
      up_to_date: false,
      current_version: "0.2.0",
      remote_version: "0.2.1",
      remote_commit: "abcdef1234567890abcdef1234567890abcdef12",
      artifact_url: "https://github.com/zany130/DiscDeck/releases/download/discdeck-dev/DiscDeck-phase0-dev-abcdef1.zip",
      zip_sha256: "ab".repeat(32),
    });
    expect(notice.message).toBe("Version 0.2.1 is published. You are running 0.2.0.");
    expect(notice.offer?.label).toBe("0.2.1");
    expect(notice.offer?.version).toBe("0.2.1");
  });

  it("shows the version ahead of the build hash", () => {
    expect(versionLabel("0.2.0", "e7b142d27b5c02fb4fed02ae19b2d011db61d95a")).toBe("Version 0.2.0 · build e7b142d");
  });
});
