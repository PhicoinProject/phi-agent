// @vitest-environment jsdom
// Guards the rounded, foundation-blue look: no bevel shadows or squared chrome come back, the
// brand accent is the foundation blue, and the sidebar mark is the foundation logo glyph.
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { Button } from "@phi/ui/ui/components/button";
import { Card } from "@phi/ui/ui/components/card";
import { Input } from "@phi/ui/ui/components/input";
import { act } from "react";
import { createRoot } from "react-dom/client";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function classesOf(node: React.ReactElement): string {
  const host = document.createElement("div");
  const root = createRoot(host);
  act(() => root.render(node));
  const cls = (host.firstElementChild as HTMLElement).className;
  act(() => root.unmount());
  return cls;
}

const css = readFileSync(resolve(__dirname, "index.css"), "utf8");

describe("brand look", () => {
  it("buttons are 6px-rounded (Windows 11) without bevel shadows; primary is the brand blue", () => {
    const primary = classesOf(<Button>Go</Button>);
    expect(primary).toMatch(/\brounded-md\b/);
    expect(primary).toMatch(/\bbg-brand\b/);
    expect(primary).not.toMatch(/inset_|active:invert|tracking-\[0\.2em\]/);
    const outlined = classesOf(<Button outlined>Go</Button>);
    expect(outlined).toMatch(/\brounded-md\b/);
    expect(outlined).not.toMatch(/inset_/);
  });

  it("cards are 8px layers with a hairline stroke; inputs are 6px with an accent underline on focus", () => {
    const card = classesOf(<Card />);
    expect(card).toMatch(/\brounded-lg\b/);
    expect(card).toMatch(/\bborder\b/);
    const input = classesOf(<Input />);
    expect(input).toMatch(/\brounded-md\b/);
    expect(input).toMatch(/focus-visible:border-b-brand/);
  });

  it("the palette is the foundation's: PHI BLUE accent on a deep navy canvas, 8px radius", () => {
    expect(css).toMatch(/--brand:\s*#0798fe;/);
    expect(css).toMatch(/--background-base:\s*#071b30;/);
    expect(css).toMatch(/--theme-radius:\s*0\.5rem;/);
    expect(css).toMatch(/--color-primary:\s*var\(--brand\);/);
  });

  it("the mark is the foundation logo glyph as vector SVG in the brand blue (no disc behind it)", () => {
    const svg = readFileSync(resolve(__dirname, "../public/phi-mark.svg"), "utf8");
    expect(svg).toMatch(/^<svg [^>]*viewBox="/);
    expect(svg).toContain('fill="#0798FE"');
    expect(svg).not.toMatch(/<image|<circle|base64/);
    // Two D bowls and the shared stem.
    expect(svg.match(/<path /g)).toHaveLength(2);
    expect(svg).toContain("<rect ");
    // The raster fallbacks stay the same glyph.
    const png = readFileSync(resolve(__dirname, "../public/phi-mark-64.png"));
    expect(createHash("sha256").update(png).digest("hex").slice(0, 16)).toBe("d0c647e8587650ab");
  });
});
