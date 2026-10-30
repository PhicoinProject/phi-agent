/** Browser-local voice preferences (Settings → Voice); no config key backs them. */
export const VOICE_AUTO_SEND_KEY = "phi.voice.autoSend";
export const VOICE_RELEASE_FILL_KEY = "phi.voice.releaseFill";

export function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

export function writeFlag(key: string, on: boolean): void {
  try {
    if (on) window.localStorage.setItem(key, "1");
    else window.localStorage.removeItem(key);
  } catch {
    // Storage disabled: the preference lasts for this page only.
  }
}

/** Microphone chosen in the composer's device menu; absent means the system default. */
export const MIC_DEVICE_KEY = "phi-mic-device-id";

export function readMicDeviceId(): string | null {
  try {
    return window.localStorage.getItem(MIC_DEVICE_KEY) || null;
  } catch {
    return null;
  }
}

export function writeMicDeviceId(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(MIC_DEVICE_KEY, id);
    else window.localStorage.removeItem(MIC_DEVICE_KEY);
  } catch {
    // Storage disabled: the choice lasts for this page only.
  }
}
