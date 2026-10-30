import { defineConfig, type Plugin } from "vite";
import babel from "@rolldown/plugin-babel";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";

/** React Compiler preset scoped to modules that can actually contain
 *  components/hooks (JSX syntax or a react-ish import). The preset's default
 *  code filter matches any PascalCase/use* declaration — effectively every TS
 *  module — which made the babel pass parse the whole codebase. */
function compilerPreset() {
  const preset = reactCompilerPreset();
  preset.rolldown.filter.code = /\/>|<\/|from\s*['"][^'"]*react/;
  return preset;
}
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import { fileURLToPath } from "node:url";

const configDir: string = fileURLToPath(new URL(".", import.meta.url));

export function phiUiClassicRuntime(): Plugin {
  return {
    name: "phi-ui-classic-runtime",
    enforce: "pre",
    transform(code, id) {
      const normalized = id.replaceAll("\\", "/");
      if (
        normalized.includes("/phi-ui/dist/") &&
        normalized.endsWith(".js") &&
        code.includes("React.createElement") &&
        !/import\s+(?:\*\s+as\s+)?React\b/.test(code)
      ) {
        return { code: `import * as React from "react";\n${code}`, map: null };
      }
    },
  };
}

const BACKEND = process.env.PHI_DASHBOARD_URL ?? "http://127.0.0.1:9119";

/**
 * In production the Python `phi dashboard` server injects a one-shot
 * session token into `index.html` (see `phi_cli/web_server.py`). The
 * Vite dev server serves its own `index.html`, so unless we forward that
 * token, every protected `/api/*` call 401s.
 *
 * This plugin fetches the running dashboard's `index.html` on each dev page
 * load and forwards its runtime bootstrap values into the dev HTML. No-op in
 * production builds.
 */
function hermesDevToken(): Plugin {
  const TOKEN_RE = /window\.__PHI_SESSION_TOKEN__\s*=\s*"([^"]+)"/;
  const EMBEDDED_RE =
    /window\.__PHI_DASHBOARD_EMBEDDED_CHAT__\s*=\s*(true|false)/;
  const INITIAL_PROFILE_RE =
    /window\.__PHI_INITIAL_PROFILE__\s*=\s*("(?:\\.|[^"\\])*")/;

  return {
    name: "phi:dev-session-token",
    apply: "serve",
    async transformIndexHtml() {
      try {
        const res = await fetch(BACKEND, { headers: { accept: "text/html" } });
        const html = await res.text();
        const match = html.match(TOKEN_RE);
        if (!match) {
          console.warn(
            `[phi] Could not find session token in ${BACKEND} — ` +
              `is \`phi dashboard\` running? /api calls will 401.`,
          );
          return;
        }
        const embeddedMatch = html.match(EMBEDDED_RE);
        const embeddedJs = embeddedMatch ? embeddedMatch[1] : "true";
        const initialProfileMatch = html.match(INITIAL_PROFILE_RE);
        const initialProfileJs = initialProfileMatch?.[1] ?? '""';
        return [
          {
            tag: "script",
            injectTo: "head",
            children:
              `window.__PHI_SESSION_TOKEN__="${match[1]}";` +
              `window.__PHI_DASHBOARD_EMBEDDED_CHAT__=${embeddedJs};` +
              `window.__PHI_INITIAL_PROFILE__=${initialProfileJs};`,
          },
        ];
      } catch (err) {
        console.warn(
          `[phi] Dashboard at ${BACKEND} unreachable — ` +
            `start it with \`phi dashboard\` or set PHI_DASHBOARD_URL. ` +
            `(${(err as Error).message})`,
        );
      }
    },
  };
}

export default defineConfig({
  plugins: [
    phiUiClassicRuntime(),
    react(),
    babel({ presets: [compilerPreset()] }),
    tailwindcss(),
    hermesDevToken(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(configDir, "./src"),
      "@phi/shared": path.resolve(configDir, "../apps/shared/src"),
    },
    // When @phi/ui is symlinked via `file:../../design-language`,
    // Node's module resolution would pick up shared deps from
    // design-language/node_modules/*, giving us two copies + breaking
    // hooks (useRef-of-null), webgl contexts, etc. Force everything that
    // exists in BOTH places to use the dashboard's copy.
    //
    // Don't list packages here that only exist in the DS (nanostores,
    // @nanostores/react) — Vite dedupe errors out when it can't find
    // them at the project root.
    dedupe: [
      "react",
      "react-dom",
      "@react-three/fiber",
      "@observablehq/plot",
      "three",
      "leva",
      "gsap",
    ],
  },
  build: {
    outDir: "../phi_cli/web_dist",
    emptyOutDir: true,
    // Shell stays a bit over Vite's 500 kB default after vendor splits;
    // page/xterm chunks load on demand. Keep a modest ceiling so a true
    // regression still warns.
    chunkSizeWarningLimit: 600,
    // Split heavy vendors so the first dashboard paint does not download
    // xterm/three/plot/etc. until a route actually needs them. Lazy page
    // imports in App.tsx create the route boundaries; these groups keep
    // shared node_modules out of every page chunk.
    rolldownOptions: {
      output: {
        codeSplitting: {
          minSize: 20_000,
          groups: [
            {
              name: "react-vendor",
              test: /node_modules[\\/](react|react-dom|scheduler|react-router|react-router)([\\/]|$)/,
            },
            {
              name: "xterm",
              test: /node_modules[\\/]@xterm[\\/]/,
            },
            {
              name: "computer",
              test: /node_modules[\\/](@novnc[\\/]novnc|@panzoom[\\/]panzoom)([\\/]|$)/,
            },
            {
              name: "three",
              test: /node_modules[\\/](three|@react-three)([\\/]|$)/,
            },
            {
              name: "plot",
              test: /node_modules[\\/]@observablehq[\\/]plot([\\/]|$)/,
            },
            {
              name: "motion",
              test: /node_modules[\\/](motion|framer-motion)([\\/]|$)/,
            },
            {
              name: "ui",
              test: /node_modules[\\/]@nous-research[\\/]ui([\\/]|$)/,
            },
            // Rich chat rendering loads with the pages that use it; mermaid
            // and pdf.js only on first diagram/PDF. Keep them out of vendor.
            // katex sits in markdown because mermaid shares it.
            {
              name: "markdown",
              test: /node_modules[\\/](react-markdown|remark-[^\\/]+|rehype-[^\\/]+|micromark[^\\/]*|mdast-[^\\/]+|hast-[^\\/]+|hastscript|unist-[^\\/]+|unified|vfile[^\\/]*|katex|lowlight|highlight\.js)([\\/]|$)/,
            },
            {
              name: "mermaid",
              test: /node_modules[\\/](mermaid|@mermaid-js|@braintree|@iconify|cytoscape[^\\/]*|cose-base|layout-base|dagre-d3-es|khroma|langium|chevrotain|@chevrotain|roughjs|stylis|marked|dayjs|dompurify|ts-dedent|lodash-es)([\\/]|$)/,
            },
            {
              name: "pdfjs",
              test: /node_modules[\\/]pdfjs-dist([\\/]|$)/,
            },
            {
              name: "vendor",
              test: /node_modules[\\/]/,
            },
          ],
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: BACKEND,
        ws: true,
      },
      // Same host as `phi dashboard` must serve these; Vite has no
      // dashboard-plugins/* files, so without this, plugin scripts 404
      // or receive index.html in dev.
      "/dashboard-plugins": BACKEND,
    },
  },
});
