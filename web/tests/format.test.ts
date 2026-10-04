import { describe, expect, it } from "vitest";
import { compareVersionsDesc, formatUsd, shortUrl, versionLabel } from "@/lib/format";

describe("versionLabel", () => {
  it("names Expo SDK versions the way developers do", () => {
    expect(versionLabel("expo", "v58.0.0")).toBe("SDK 58");
    expect(versionLabel("expo", "unversioned")).toBe("guides");
    expect(versionLabel("expo", "v58.1.0")).toBe("v58.1.0");
    expect(versionLabel("react-native", "0.82.0")).toBe("0.82");
    expect(versionLabel("react-native", "current")).toBe("current");
  });
});

describe("compareVersionsDesc", () => {
  it("sorts numerically, newest first, non-numeric last", () => {
    expect(["v9.0.0", "v58.0.0", "next", "v57.0.0"].sort(compareVersionsDesc)).toEqual(["v58.0.0", "v57.0.0", "v9.0.0", "next"]);
  });
});

describe("formatUsd", () => {
  it("shows sub-cent costs with enough precision", () => {
    expect(formatUsd(0.00091)).toBe("$0.00091");
    expect(formatUsd(0.0042)).toBe("$0.0042");
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(1.5)).toBe("$1.50");
  });
});

describe("shortUrl", () => {
  it("drops the scheme, anchor and trailing slash", () => {
    expect(shortUrl("https://docs.expo.dev/versions/v58.0.0/sdk/notifications/#setup")).toBe("docs.expo.dev/versions/v58.0.0/sdk/notifications");
    expect(shortUrl("not a url")).toBe("not a url");
  });
});
