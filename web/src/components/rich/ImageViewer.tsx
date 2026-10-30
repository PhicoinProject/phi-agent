import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@phi/ui/ui/components/button";
import { useRichStrings } from "./strings";

const MIN_SCALE = 0.05;
const MAX_SCALE = 16;
const STEP = 1.25;

function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

/** Scale an image in fit mode is shown at, relative to its natural size. */
function fitScale(image: HTMLImageElement | null): number {
  return image && image.naturalWidth ? image.clientWidth / image.naturalWidth : 1;
}

function pointerDistance(points: Map<number, { x: number; y: number }>): number {
  const [a, b] = [...points.values()];
  return a && b ? Math.hypot(a.x - b.x, a.y - b.y) : 0;
}

/**
 * Image fit to the panel, with zoom buttons, wheel zoom, two-finger pinch and
 * mouse drag to pan. `src` is always a URL for <img>; SVG files arrive here
 * as a data URL too, so their markup never becomes page DOM.
 */
export function ImageViewer({ src, alt }: { src: string; alt: string }) {
  const s = useRichStrings();
  // null = fit to the panel; otherwise a multiple of the natural size.
  const [scale, setScale] = useState<number | null>(null);
  const [naturalWidth, setNaturalWidth] = useState(0);
  const frameRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinchStart = useRef<{ distance: number; scale: number } | null>(null);

  const zoomBy = (factor: number) =>
    setScale((current) => clampScale((current ?? fitScale(imageRef.current)) * factor));

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    // Non-passive so the wheel zooms the image instead of scrolling the page.
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const factor = event.deltaY < 0 ? STEP : 1 / STEP;
      setScale((current) => clampScale((current ?? fitScale(imageRef.current)) * factor));
    };
    frame.addEventListener("wheel", onWheel, { passive: false });
    return () => frame.removeEventListener("wheel", onWheel);
  }, []);

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.current.size === 2) {
      pinchStart.current = { distance: pointerDistance(pointers.current), scale: scale ?? fitScale(imageRef.current) };
    }
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const previous = pointers.current.get(event.pointerId);
    if (!previous) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const pinch = pinchStart.current;
    if (pinch && pointers.current.size === 2 && pinch.distance > 0) {
      setScale(clampScale(pinch.scale * (pointerDistance(pointers.current) / pinch.distance)));
    } else if (event.pointerType === "mouse" && event.buttons === 1 && frameRef.current) {
      frameRef.current.scrollLeft -= event.clientX - previous.x;
      frameRef.current.scrollTop -= event.clientY - previous.y;
    }
  };

  const onPointerEnd = (event: ReactPointerEvent<HTMLDivElement>) => {
    pointers.current.delete(event.pointerId);
    if (pointers.current.size < 2) pinchStart.current = null;
  };

  const zoomed = scale !== null && naturalWidth > 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-1 border-b border-border px-3 py-1.5 text-xs text-muted-foreground">
        <Button ghost size="xs" type="button" onClick={() => zoomBy(1 / STEP)} aria-label={s.zoomOut} title={s.zoomOut}>
          <ZoomOut />
        </Button>
        <span className="w-12 text-center tabular-nums" data-zoom>
          {scale === null ? s.zoomFit : `${Math.round(scale * 100)}%`}
        </span>
        <Button ghost size="xs" type="button" onClick={() => zoomBy(STEP)} aria-label={s.zoomIn} title={s.zoomIn}>
          <ZoomIn />
        </Button>
        <Button ghost size="xs" type="button" onClick={() => setScale(null)} aria-label={s.zoomFit} title={s.zoomFit}>
          <Maximize2 />
        </Button>
      </div>
      <div
        ref={frameRef}
        className="flex min-h-0 flex-1 overflow-auto p-3 [touch-action:pan-x_pan-y]"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        onPointerLeave={onPointerEnd}
      >
        <img
          ref={imageRef}
          src={src}
          alt={alt}
          draggable={false}
          onLoad={(event) => setNaturalWidth(event.currentTarget.naturalWidth)}
          className={zoomed ? "m-auto max-w-none select-none" : "m-auto max-h-full max-w-full object-contain select-none"}
          style={zoomed ? { width: naturalWidth * scale } : undefined}
        />
      </div>
    </div>
  );
}
