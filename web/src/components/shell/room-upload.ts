// Uploads a picked photo/file into a room's folder for the phone composer and the room sheet.

import { api } from "@/lib/api";
import { ApiError } from "@/lib/api-error";

const MAX_RENAMES = 20;

/** Uploads into the room folder without overwriting: photo.png, then photo-1.png, photo-2.png, … */
export async function uploadIntoRoom(dir: string, file: File): Promise<string> {
  const base = dir.replace(/\/+$/, "");
  const dot = file.name.lastIndexOf(".");
  const [stem, ext] = dot > 0 ? [file.name.slice(0, dot), file.name.slice(dot)] : [file.name, ""];
  for (let n = 0; ; n++) {
    const path = `${base}/${n ? `${stem}-${n}${ext}` : file.name}`;
    try {
      return (await api.uploadFile(path, file, false)).path || path;
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409) || n >= MAX_RENAMES) throw e;
    }
  }
}
