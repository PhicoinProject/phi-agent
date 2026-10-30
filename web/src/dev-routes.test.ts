// The dev-only fixture routes are gone: no /dev/rich or /dev/voice-computer
// route, no page modules behind them, and no strings only they used.

import { describe, expect, it } from "vitest";
import appSource from "./App.tsx?raw";
import { en } from "./i18n/en";

describe("dev fixture routes", () => {
  it("are not routed", () => {
    expect(appSource).not.toContain("/dev/rich");
    expect(appSource).not.toContain("/dev/voice-computer");
    expect(appSource).not.toContain("RichDemoPage");
    expect(appSource).not.toContain("VoiceComputerDevPage");
  });

  it("have no page modules left", () => {
    const pages = Object.keys(import.meta.glob("./pages/*.tsx"));
    expect(pages.length).toBeGreaterThan(0);
    expect(pages).not.toContain("./pages/RichDemoPage.tsx");
    expect(pages).not.toContain("./pages/VoiceComputerDevPage.tsx");
  });

  it("leave no unused strings behind", () => {
    expect(en.rich).not.toHaveProperty("demoReplay");
    expect(en.voiceComputer).not.toHaveProperty("devTitle");
  });
});
