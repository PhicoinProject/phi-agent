import { useEffect, useRef, useState, type FormEvent } from "react";
import { ChevronLeft, ChevronRight, Search, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@phi/ui/ui/components/button";
import { Input } from "@phi/ui/ui/components/input";
import { Spinner } from "@phi/ui/ui/components/spinner";
import { fill, useRichStrings } from "./strings";

type PdfModule = typeof import("pdfjs-dist");
type PdfLoadingTask = ReturnType<PdfModule["getDocument"]>;
type PdfDocument = Awaited<PdfLoadingTask["promise"]>;

let pdfLoader: Promise<PdfModule> | null = null;

/** pdf.js and its worker load on first PDF only; the worker is a bundled asset. */
function loadPdfjs(): Promise<PdfModule> {
  pdfLoader ??= Promise.all([
    import("pdfjs-dist"),
    import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
  ]).then(([pdfjs, worker]) => {
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
    return pdfjs;
  });
  return pdfLoader;
}

// Lower-cased plain text per page, filled lazily by search.
const pageTextCache = new WeakMap<PdfDocument, Map<number, string>>();

async function pageText(doc: PdfDocument, pageNumber: number): Promise<string> {
  let pages = pageTextCache.get(doc);
  if (!pages) {
    pages = new Map();
    pageTextCache.set(doc, pages);
  }
  const cached = pages.get(pageNumber);
  if (cached !== undefined) return cached;
  const content = await (await doc.getPage(pageNumber)).getTextContent();
  const text = content.items
    .map((item) => ("str" in item ? item.str + (item.hasEOL ? "\n" : "") : ""))
    .join("")
    .replace(/\s+/g, " ")
    .toLowerCase();
  pages.set(pageNumber, text);
  return text;
}

/** Page numbers whose text contains `needle` (already lower-cased). */
export async function searchPdf(doc: PdfDocument, needle: string): Promise<number[]> {
  const found: number[] = [];
  for (let pageNumber = 1; pageNumber <= doc.numPages; pageNumber += 1) {
    if ((await pageText(doc, pageNumber)).includes(needle)) found.push(pageNumber);
  }
  return found;
}

const MIN_SCALE = 0.25;
const MAX_SCALE = 5;
const SCALE_STEP = 1.25;

function usePdfDocument(data: Uint8Array): { doc: PdfDocument | null; failed: boolean } {
  const [state, setState] = useState<{ doc: PdfDocument | null; failed: boolean }>({ doc: null, failed: false });

  useEffect(() => {
    let cancelled = false;
    let task: PdfLoadingTask | null = null;
    loadPdfjs()
      .then((pdfjs) => {
        if (cancelled) return null;
        // pdf.js transfers the buffer to its worker; hand it a copy.
        task = pdfjs.getDocument({ data: data.slice() });
        return task.promise;
      })
      .then((doc) => {
        if (!cancelled && doc) setState({ doc, failed: false });
      })
      .catch(() => {
        if (!cancelled) setState({ doc: null, failed: true });
      });
    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [data]);

  return state;
}

/** One page at a time on a canvas, with page nav, zoom and text search. */
export function PdfViewer({ data }: { data: Uint8Array }) {
  const s = useRichStrings();
  const { doc, failed } = usePdfDocument(data);
  const [page, setPage] = useState(1);
  const [scale, setScale] = useState(1.25);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<{ needle: string; pages: number[]; index: number } | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!doc) return;
    let cancelled = false;
    let render: { cancel(): void; promise: Promise<void> } | null = null;
    doc
      .getPage(page)
      .then((pdfPage) => {
        const canvas = canvasRef.current;
        if (cancelled || !canvas) return;
        const ratio = window.devicePixelRatio || 1;
        const viewport = pdfPage.getViewport({ scale: scale * ratio });
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = `${Math.floor(viewport.width / ratio)}px`;
        render = pdfPage.render({ canvas, viewport });
        return render.promise;
      })
      // A superseded render rejects with a cancellation; the next one takes over.
      .catch(() => undefined);
    return () => {
      cancelled = true;
      render?.cancel();
    };
  }, [doc, page, scale]);

  const runSearch = async (event: FormEvent) => {
    event.preventDefault();
    const needle = query.trim().replace(/\s+/g, " ").toLowerCase();
    if (!doc || !needle) {
      setSearch(null);
      return;
    }
    // Enter again on the same query steps to the next matching page.
    if (search?.needle === needle && search.pages.length > 0) {
      const index = (search.index + 1) % search.pages.length;
      setSearch({ ...search, index });
      setPage(search.pages[index]);
      return;
    }
    const pages = await searchPdf(doc, needle);
    setSearch({ needle, pages, index: 0 });
    if (pages.length > 0) setPage(pages[0]);
  };

  if (failed) return <p className="p-4 text-sm text-destructive">{s.loadFailed}</p>;
  if (!doc) {
    return (
      <p className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
        <Spinner /> {s.loading}
      </p>
    );
  }

  const total = doc.numPages;
  return (
    <div className="flex h-full min-h-0 flex-col" data-pdf-pages={total}>
      <div className="flex flex-wrap items-center gap-1 border-b border-border px-3 py-1.5 text-xs text-muted-foreground">
        <Button ghost size="xs" type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label={s.previousPage} title={s.previousPage}>
          <ChevronLeft />
        </Button>
        <span className="tabular-nums" data-pdf-page>
          {fill(s.pageOf, { page, total })}
        </span>
        <Button ghost size="xs" type="button" disabled={page >= total} onClick={() => setPage(page + 1)} aria-label={s.nextPage} title={s.nextPage}>
          <ChevronRight />
        </Button>
        <span className="mx-1 h-4 border-l border-border" />
        <Button ghost size="xs" type="button" disabled={scale <= MIN_SCALE} onClick={() => setScale(Math.max(MIN_SCALE, scale / SCALE_STEP))} aria-label={s.zoomOut} title={s.zoomOut}>
          <ZoomOut />
        </Button>
        <span className="w-10 text-center tabular-nums">{Math.round(scale * 100)}%</span>
        <Button ghost size="xs" type="button" disabled={scale >= MAX_SCALE} onClick={() => setScale(Math.min(MAX_SCALE, scale * SCALE_STEP))} aria-label={s.zoomIn} title={s.zoomIn}>
          <ZoomIn />
        </Button>
        <form role="search" onSubmit={(event) => void runSearch(event)} className="ml-auto flex items-center gap-1">
          <Search className="h-3.5 w-3.5" aria-hidden />
          <Input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={s.searchDocument}
            aria-label={s.searchDocument}
            className="h-7 w-40 text-xs"
          />
          {search && (
            <span className="tabular-nums" aria-live="polite" data-pdf-search>
              {search.pages.length === 0
                ? s.searchNoMatches
                : fill(s.searchMatch, { index: search.index + 1, count: search.pages.length })}
            </span>
          )}
        </form>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        <canvas ref={canvasRef} className="mx-auto block shadow" />
      </div>
    </div>
  );
}
