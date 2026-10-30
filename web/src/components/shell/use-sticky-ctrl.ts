// The phone key bar's one-shot Ctrl latch, shared with keys typed on the soft
// keyboard: the next key (from either) gets Ctrl applied, then the latch releases.

import { useCallback, useRef, useState } from "react";
import { applyCtrl } from "./MobileKeyBar";

export function useStickyCtrl() {
  const [active, setActive] = useState(false);
  const latched = useRef(false);
  const set = useCallback((next: boolean) => {
    latched.current = next;
    setActive(next);
  }, []);
  // A ref so the PTY effect can call it without re-subscribing.
  const applyRef = useRef((data: string) => {
    if (!latched.current) return data;
    latched.current = false;
    setActive(false);
    return applyCtrl(data);
  });
  return { active, set, applyRef };
}
