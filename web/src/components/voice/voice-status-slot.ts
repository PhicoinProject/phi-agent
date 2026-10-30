/**
 * Where a mic inside a composer shows its recording status (waveform, time, partial text): an
 * element the composer lays over its text field. `undefined` = no composer around (the mic is
 * standalone and shows its own floating overlay); `null` = the slot is not mounted yet.
 */
import { createContext, useContext } from "react";

export const VoiceStatusSlot = createContext<HTMLElement | null | undefined>(undefined);

export function useVoiceStatusSlot(): HTMLElement | null | undefined {
  return useContext(VoiceStatusSlot);
}
