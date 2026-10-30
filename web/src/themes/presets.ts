import { parseColor, THEME_PRESET_PALETTES, type ThemePresetPalette } from "@phi/shared";
import type { DashboardTheme, ThemePalette, ThemeTypography, ThemeLayout } from "./types";

/**
 * Built-in dashboard themes.
 *
 * Each theme defines its own palette, typography, and layout so switching
 * themes produces visible changes beyond just color — fonts, density, and
 * corner-radius all shift to match the theme's personality.
 *
 * Theme names must stay in sync with the backend's
 * `_BUILTIN_DASHBOARD_THEMES` list in `phi_cli/web_server.py`.
 */

// ---------------------------------------------------------------------------
// Shared typography / layout presets
// ---------------------------------------------------------------------------

/** Default system stack — neutral, safe fallback for every platform. */
const SYSTEM_SANS =
  'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
const SYSTEM_MONO =
  'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace';

/**
 * Phi Agent brand typography (see the visual identity manual):
 *   Spectral — headings, serif
 *   Figtree  — body, 16px on web
 *   DM Mono  — monospace
 * Each falls back to the system stack so a blocked font CDN degrades
 * to something readable rather than to Times.
 */
const BRAND_SANS = `"Figtree", ${SYSTEM_SANS}`;
const BRAND_SERIF = `"Spectral", Georgia, "Times New Roman", serif`;
const BRAND_MONO = `"DM Mono", ${SYSTEM_MONO}`;
const BRAND_FONT_URL = "";

const DEFAULT_TYPOGRAPHY: ThemeTypography = {
  fontSans: BRAND_SANS,
  fontMono: BRAND_MONO,
  fontDisplay: BRAND_SERIF,
  fontUrl: BRAND_FONT_URL,
  baseSize: "16px",
  lineHeight: "1.55",
  letterSpacing: "0",
};

const DEFAULT_LAYOUT: ThemeLayout = {
  radius: "0.5rem",
  density: "comfortable",
};

export function webPresetFromShared(preset: ThemePresetPalette): Omit<ThemePalette, "noiseOpacity"> {
  const colors = preset.darkColors ?? preset.colors;
  const [red, green, blue] = parseColor(colors.midground ?? colors.ring) ?? [255, 255, 255];
  return {
    background: { hex: colors.background, alpha: 1 },
    midground: { hex: colors.primary, alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: `rgba(${red}, ${green}, ${blue}, 0.3)`,
  };
}

// ---------------------------------------------------------------------------
// Themes
// ---------------------------------------------------------------------------

export const defaultTheme: DashboardTheme = {
  name: "default",
  label: "Phi Blue",
  description: "Phi Lab foundation palette: deep navy canvas, PHI BLUE accent, Windows 11-style rounded layers",
  palette: {
    // Deep navy from MIDNIGHT #054069: still the brand's blue family, not black.
    background: { hex: "#071b30", alpha: 1 },
    // Cool wash for body copy and UI chrome.
    midground: { hex: "#eef4fb", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    // PHI BLUE #0798FE glow replaces the old amber.
    warmGlow: "rgba(7, 152, 254, 0.32)",
    noiseOpacity: 1,
  },
  typography: DEFAULT_TYPOGRAPHY,
  layout: DEFAULT_LAYOUT,
  terminalBackground: "#04121f",
};

export const midnightTheme: DashboardTheme = {
  name: "midnight",
  label: "Midnight",
  description: "Deep blue-violet with cool accents",
  palette: {
    ...webPresetFromShared(THEME_PRESET_PALETTES.midnight),
    noiseOpacity: 0.8,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Inter", ${SYSTEM_SANS}`,
    fontMono: `"JetBrains Mono", ${SYSTEM_MONO}`,
    letterSpacing: "-0.005em",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0.75rem",
  },
};

export const emberTheme: DashboardTheme = {
  name: "ember",
  label: "Ember",
  description: "Warm crimson and bronze — forge vibes",
  palette: {
    ...webPresetFromShared(THEME_PRESET_PALETTES.ember),
    noiseOpacity: 1,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Spectral", Georgia, "Times New Roman", serif`,
    fontMono: `"IBM Plex Mono", ${SYSTEM_MONO}`,
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0.25rem",
  },
  colorOverrides: {
    destructive: "#c92d0f",
    warning: "#f97316",
  },
};

export const monoTheme: DashboardTheme = {
  name: "mono",
  label: "Mono",
  description: "Clean grayscale — minimal and focused",
  palette: {
    ...webPresetFromShared(THEME_PRESET_PALETTES.mono),
    noiseOpacity: 0.6,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"IBM Plex Sans", ${SYSTEM_SANS}`,
    fontMono: `"IBM Plex Mono", ${SYSTEM_MONO}`,
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0",
  },
};

export const cyberpunkTheme: DashboardTheme = {
  name: "cyberpunk",
  label: "Cyberpunk",
  description: "Neon green on black — matrix terminal",
  palette: {
    ...webPresetFromShared(THEME_PRESET_PALETTES.cyberpunk),
    noiseOpacity: 1.2,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Share Tech Mono", "JetBrains Mono", ${SYSTEM_MONO}`,
    fontMono: `"Share Tech Mono", "JetBrains Mono", ${SYSTEM_MONO}`,
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0",
  },
  colorOverrides: {
    success: "#00ff88",
    warning: "#2AA6FE",
    destructive: "#ff0055",
  },
};

export const roseTheme: DashboardTheme = {
  name: "rose",
  label: "Rosé",
  description: "Soft pink and warm ivory — easy on the eyes",
  palette: {
    background: { hex: "#1a0f15", alpha: 1 },
    midground: { hex: "#ffd4e1", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(249, 168, 212, 0.3)",
    noiseOpacity: 0.9,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Fraunces", Georgia, serif`,
    fontMono: `"DM Mono", ${SYSTEM_MONO}`,
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "1rem",
  },
};

/** Light mode — PHI BLUE accents on a WASH canvas. */
export const phiLightTheme: DashboardTheme = {
  name: "phi-light",
  label: "Phi Light",
  description: "Light mode — PHI BLUE accents on a wash canvas",
  palette: {
    // WASH #F7F9FB canvas, PHI BLUE #0798FE ink, per the VI manual.
    background: { hex: "#f7f9fb", alpha: 1 },
    midground: { hex: "#0798fe", alpha: 1 },
    foreground: { hex: "#0e0f0c", alpha: 0 },
    warmGlow: "rgba(7, 152, 254, 0.12)",
    noiseOpacity: 0,
  },
  typography: DEFAULT_TYPOGRAPHY,
  layout: DEFAULT_LAYOUT,
  terminalBackground: "#ffffff",
  // INK #0E0F0C
  terminalForeground: "#0e0f0c",
  seriesColors: {
    // MIDNIGHT #054069 / PHI BLUE #0798FE
    inputTokenAccent: "#054069",
    outputTokenAccent: "#0798fe",
  },
  swatchColors: ["#0e0f0c", "#0798fe", "#f7f9fb"],
};

/**
 * Same look as ``defaultTheme`` but with a larger root font size, looser
 * line-height, and ``spacious`` density so every rem-based size in the
 * dashboard scales up. For users who find the default 15px UI too dense.
 */
export const defaultLargeTheme: DashboardTheme = {
  name: "default-large",
  label: "Phi Blue (Large)",
  description: "Phi Blue with bigger fonts and roomier spacing",
  palette: defaultTheme.palette,
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    baseSize: "18px",
    lineHeight: "1.65",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    density: "spacious",
  },
};

export const BUILTIN_THEMES: Record<string, DashboardTheme> = {
  default: defaultTheme,
  "default-large": defaultLargeTheme,
  "phi-light": phiLightTheme,
  midnight: midnightTheme,
  ember: emberTheme,
  mono: monoTheme,
  cyberpunk: cyberpunkTheme,
  rose: roseTheme,
};
