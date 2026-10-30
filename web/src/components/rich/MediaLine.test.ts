import { describe, expect, it } from "vitest";

import { fileKind, isPreviewablePath } from "./file-kind";
import { mediaLinePath, parseMediaSegments } from "./MediaLine";

describe("mediaLinePath", () => {
  it.each([
    ["MEDIA:/tmp/a.png", "/tmp/a.png"],
    ["  MEDIA: /home/me/.phi/cache/screenshots/browser_screenshot_ecc.png  ", "/home/me/.phi/cache/screenshots/browser_screenshot_ecc.png"],
    ["`MEDIA:/tmp/a.png`", "/tmp/a.png"],
    ['"MEDIA:C:\\files\\a.png"', "C:\\files\\a.png"],
    ["'MEDIA:/tmp/report.pdf'", "/tmp/report.pdf"],
    ["MEDIA:/tmp/archive.bin", "/tmp/archive.bin"],
  ])("parses %j as a MEDIA directive", (line, path) => {
    expect(mediaLinePath(line)).toEqual({ path, source: "media" });
  });

  it.each([
    "here is MEDIA:/tmp/a.png for you",
    "the media: section is empty",
    "MEDIA:",
    "/tmp/no-extension",
    "/tmp/archive.bin",
    "//cdn.example.com/a.png",
    "see /tmp/a.png",
    "https://example.com/a.png",
  ])("leaves %j as prose", (line) => {
    expect(mediaLinePath(line)).toBeNull();
  });

  it.each([
    ["/tmp/plot.png", "/tmp/plot.png"],
    ["~/notes/today.md", "~/notes/today.md"],
    ["`C:/work/report.pdf`", "C:/work/report.pdf"],
  ])("detects a bare previewable path line %j", (line, path) => {
    expect(mediaLinePath(line)).toEqual({ path, source: "path" });
  });
});

describe("parseMediaSegments", () => {
  it("splits prose and file lines and drops the voice directive", () => {
    const text = "Report is ready:\nMEDIA:/tmp/report.pdf\n[[audio_as_voice]]\nDone.";
    expect(parseMediaSegments(text)).toEqual([
      { type: "markdown", text: "Report is ready:" },
      { type: "file", path: "/tmp/report.pdf", source: "media" },
      { type: "markdown", text: "Done." },
    ]);
  });

  it("keeps paths inside fenced code as code", () => {
    const text = "```text\nMEDIA:/tmp/a.png\n/tmp/b.png\n```\n/tmp/c.png";
    expect(parseMediaSegments(text)).toEqual([
      { type: "markdown", text: "```text\nMEDIA:/tmp/a.png\n/tmp/b.png\n```" },
      { type: "file", path: "/tmp/c.png", source: "path" },
    ]);
  });

  it("treats an unterminated fence as code to the end", () => {
    const text = "~~~\n/tmp/a.png";
    expect(parseMediaSegments(text)).toEqual([{ type: "markdown", text }]);
  });

  it("holds back the unfinished last line while streaming", () => {
    expect(parseMediaSegments("Look:\nMEDIA:/tmp/a.pn", { streaming: true })).toEqual([
      { type: "markdown", text: "Look:\nMEDIA:/tmp/a.pn" },
    ]);
    expect(parseMediaSegments("Look:\nMEDIA:/tmp/a.png\n", { streaming: true })).toEqual([
      { type: "markdown", text: "Look:" },
      { type: "file", path: "/tmp/a.png", source: "media" },
    ]);
  });
});

describe("fileKind", () => {
  it.each([
    ["/a/b.PNG", "image"],
    ["/a/b.svg", "image"],
    ["/a/b.avif", "image"],
    ["/a/b.mp3", "audio"],
    ["/a/b.webm", "video"],
    ["/a/b.pdf", "pdf"],
    ["/a/b.md", "markdown"],
    ["/a/b.py", "code"],
    ["/a/b.log", "text"],
    ["/a/b.zip", "other"],
    ["/a/.bashrc", "other"],
  ])("%s → %s", (path, kind) => {
    expect(fileKind(path)).toBe(kind);
  });

  it("only previewable kinds count as previewable", () => {
    expect(isPreviewablePath("/a/b.zip")).toBe(false);
    expect(isPreviewablePath("/a/b.jpeg")).toBe(true);
  });
});
