import { useEffect, useState } from "react";
import { api, PHI_BASE_PATH } from "@/lib/api";
import type { ManagedFileReadResponse } from "@/lib/api-files";

/**
 * URL for a managed-files GET route the browser loads itself (media element,
 * download link) where no auth header can be attached. Loopback mode carries
 * the page's session token as `?token=`; gated mode relies on the cookie.
 */
function fileRouteUrl(route: "stream" | "download", path: string): string {
  const params = new URLSearchParams({ path });
  const token = typeof window === "undefined" ? "" : window.__PHI_SESSION_TOKEN__;
  if (token) params.set("token", token);
  return `${PHI_BASE_PATH}/api/files/${route}?${params.toString()}`;
}

/** Range-capable source for <audio>/<video>. With a page token the download route serves it:
 * it answers a media request (`Sec-Fetch-Dest: audio|video`) inline with Range support, while
 * /api/files/stream deliberately takes no credential in its URL (header-only, for Electron). */
export function fileStreamUrl(path: string): string {
  const token = typeof window === "undefined" ? "" : window.__PHI_SESSION_TOKEN__;
  return fileRouteUrl(token ? "download" : "stream", path);
}

export function fileDownloadUrl(path: string): string {
  return fileRouteUrl("download", path);
}

/** Bytes carried by a base64 `data:` URL (the /api/files/read payload). */
export function dataUrlBytes(dataUrl: string): Uint8Array {
  const comma = dataUrl.indexOf(",");
  const meta = dataUrl.slice(0, comma);
  const body = dataUrl.slice(comma + 1);
  if (!meta.endsWith(";base64")) {
    return new TextEncoder().encode(decodeURIComponent(body));
  }
  const binary = atob(body);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export function dataUrlText(dataUrl: string): string {
  return new TextDecoder().decode(dataUrlBytes(dataUrl));
}

export type ManagedFileState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; file: ManagedFileReadResponse };

const LOADING: ManagedFileState = { status: "loading" };

/** `/api/files/read` for one path; reverts to loading when the path changes. */
export function useManagedFile(path: string): ManagedFileState {
  const [loaded, setLoaded] = useState<{ path: string; state: ManagedFileState } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.readFile(path).then(
      (file) => {
        if (!cancelled) setLoaded({ path, state: { status: "ready", file } });
      },
      () => {
        if (!cancelled) setLoaded({ path, state: { status: "error" } });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [path]);

  return loaded?.path === path ? loaded.state : LOADING;
}
