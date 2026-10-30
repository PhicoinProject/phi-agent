/**
 * Live microphone level as a strip of bars, newest on the right. Drawn on a small canvas in the
 * element's text colour; levels arrive from the dictation `LevelMeter` (not React state) and are
 * coalesced into at most one draw per animation frame. Reduced motion shows the live level
 * on every bar instead of a scrolling history; it is never a decorative pattern.
 */
import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

import type { LevelMeter } from "./useDictation";

export interface MicWaveformProps {
  meter: LevelMeter;
  /** Stop following the meter (finalizing): the last bars stay, faded. */
  frozen?: boolean;
  bars?: number;
  /** CSS pixels. */
  width?: number;
  height?: number;
  className?: string;
}

const MIN_BAR = 2;
const GAP = 1;

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function MicWaveform({ meter, frozen = false, bars = 16, width = 36, height = 16, className }: MicWaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const levels = useRef<number[]>([]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (levels.current.length !== bars) levels.current = new Array<number>(bars).fill(0);

    const draw = (values: readonly number[]) => {
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = getComputedStyle(canvas).color || "#888";
      const step = width / values.length;
      values.forEach((value, i) => {
        const h = Math.max(MIN_BAR, Math.min(1, value) * height);
        ctx.fillRect(i * step, (height - h) / 2, Math.max(1, step - GAP), h);
      });
    };

    draw(levels.current);
    if (frozen) return;
    // Reduced motion: still the real level (it is information, not decoration), but every bar shows
    // the current level instead of a scrolling history.
    const still = prefersReducedMotion();
    let frame = 0;
    const unsubscribe = meter.subscribe((level) => {
      levels.current = still ? levels.current.map(() => level) : [...levels.current.slice(1), level];
      frame ||= requestAnimationFrame(() => {
        frame = 0;
        draw(levels.current);
      });
    });
    return () => {
      unsubscribe();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [bars, frozen, height, meter, width]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={cn("block shrink-0 transition-opacity", frozen && "opacity-40", className)}
      style={{ height, width }}
    />
  );
}
