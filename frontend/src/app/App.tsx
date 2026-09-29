import { useState, useRef, useCallback, useEffect } from "react";
import { Upload, Cpu, Zap, ImageIcon, AlertTriangle, ChevronDown, Loader2, SplitSquareHorizontal, BarChart3, Clock, Layers } from "lucide-react";
import { API_BASE_URL, buildProcessFormData, errorMessage, parseServerTiming } from "./api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ProcessResult {
  output_image: string; // base64 data URL
  execution_time_ms: number;
  total_time_ms: number;
  backend: string;
  width: number;
  height: number;
}

type FilterType = "box_blur" | "sobel_edge";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function clamp(val: number, min: number, max: number) {
  return Math.min(Math.max(val, min), max);
}

function nearestOdd(n: number): number {
  return n % 2 === 0 ? n + 1 : n;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function TerminalLine({ label, value, accent = false, dim = false }: {
  label: string;
  value: string;
  accent?: boolean;
  dim?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-2 font-mono text-sm leading-relaxed">
      <span className={`shrink-0 ${dim ? "text-[#3d4f63]" : "text-[#4a6070]"}`}>{label}</span>
      <span className="flex-1 border-b border-dashed border-[#1a2a36] mb-[3px]" />
      <span className={accent ? "text-emerald-400 font-semibold" : "text-[#8fa8bf]"}>{value}</span>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, sub, color }: {
  icon: React.ElementType;
  label: string;
  value: string;
  sub: string;
  color: string;
}) {
  return (
    <div className="relative flex flex-col gap-2 rounded-lg border border-[rgba(99,102,241,0.12)] bg-[#0b1019] p-4 overflow-hidden">
      <div className={`absolute top-0 left-0 h-[2px] w-full ${color}`} />
      <div className="flex items-center gap-2">
        <Icon size={14} className="text-muted-foreground" />
        <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">{label}</span>
      </div>
      <p className="font-mono text-2xl font-semibold text-foreground leading-none">{value}</p>
      <p className="font-mono text-xs text-muted-foreground">{sub}</p>
    </div>
  );
}

// ─── Image Comparison Slider ──────────────────────────────────────────────────

function ComparisonSlider({ original, processed }: { original: string; processed: string }) {
  const [splitPct, setSplitPct] = useState(50);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const handleMove = useCallback((clientX: number) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const pct = clamp(((clientX - rect.left) / rect.width) * 100, 2, 98);
    setSplitPct(pct);
  }, []);

  const onMouseDown = (e: React.MouseEvent) => {
    dragging.current = true;
    e.preventDefault();
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => { if (dragging.current) handleMove(e.clientX); };
    const onUp = () => { dragging.current = false; };
    const onTouchMove = (e: TouchEvent) => { if (dragging.current) handleMove(e.touches[0].clientX); };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("touchmove", onTouchMove, { passive: true });
    window.addEventListener("touchend", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onUp);
    };
  }, [handleMove]);

  return (
    <div
      ref={containerRef}
      className="relative w-full select-none overflow-hidden rounded-lg cursor-col-resize"
      style={{ touchAction: "none" }}
      onMouseDown={onMouseDown}
      onTouchStart={(e) => { dragging.current = true; handleMove(e.touches[0].clientX); }}
    >
      {/* Processed (bottom layer, full width) */}
      <img src={processed} alt="Processed" className="block w-full h-auto" draggable={false} />

      {/* Original (clipped overlay) */}
      <div
        className="absolute inset-0 overflow-hidden"
        style={{ width: `${splitPct}%` }}
      >
        <img src={original} alt="Original" className="block h-full w-auto max-w-none" draggable={false}
          style={{ width: `${100 / (splitPct / 100)}%`, maxWidth: "none" }}
        />
      </div>

      {/* Divider */}
      <div
        className="absolute inset-y-0 flex items-center justify-center"
        style={{ left: `${splitPct}%`, transform: "translateX(-50%)" }}
      >
        <div className="w-[2px] h-full bg-emerald-400 opacity-90 shadow-[0_0_8px_#10b981]" />
        <div className="absolute flex items-center justify-center w-8 h-8 rounded-full bg-emerald-400 shadow-[0_0_16px_#10b981] cursor-col-resize">
          <SplitSquareHorizontal size={14} className="text-black" />
        </div>
      </div>

      {/* Labels */}
      <div className="absolute bottom-2 left-3 font-mono text-[10px] uppercase tracking-widest bg-black/60 text-emerald-400 px-2 py-0.5 rounded">
        Original
      </div>
      <div className="absolute bottom-2 right-3 font-mono text-[10px] uppercase tracking-widest bg-black/60 text-indigo-400 px-2 py-0.5 rounded">
        Processed
      </div>
    </div>
  );
}

// ─── Main App ────────────────────────────────────────────────────────────────

export default function App() {
  const [isDragging, setIsDragging] = useState(false);
  const [originalFile, setOriginalFile] = useState<File | null>(null);
  const [originalURL, setOriginalURL] = useState<string | null>(null);
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [filter, setFilter] = useState<FilterType>("box_blur");
  const [kernelSize, setKernelSize] = useState(5);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    return () => {
      if (originalURL) URL.revokeObjectURL(originalURL);
    };
  }, [originalURL]);

  useEffect(() => {
    return () => {
      if (result?.output_image) URL.revokeObjectURL(result.output_image);
    };
  }, [result]);

  const pixelsPerSec =
    result && result.execution_time_ms > 0
      ? Math.round((result.width * result.height) / (result.execution_time_ms / 1000))
      : null;

  // ── File handling ─────────────────────────────────────────────────────────

  const loadFile = (file: File) => {
    if (!file.type.startsWith("image/")) {
      setError("File must be an image (PNG, JPEG, WebP, etc.).");
      return;
    }
    setError(null);
    setResult((prev) => {
      if (prev?.output_image) URL.revokeObjectURL(prev.output_image);
      return null;
    });
    setOriginalFile(file);
    setOriginalURL((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return URL.createObjectURL(file);
    });
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) loadFile(file);
  };

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) loadFile(file);
  };

  // ── Kernel slider (odd only) ──────────────────────────────────────────────

  const handleKernelChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = parseInt(e.target.value, 10);
    setKernelSize(nearestOdd(raw));
  };

  // ── Process ───────────────────────────────────────────────────────────────

  const processImage = async () => {
    if (!originalFile) return;
    setIsProcessing(true);
    setError(null);
    setResult((prev) => {
      if (prev?.output_image) URL.revokeObjectURL(prev.output_image);
      return null;
    });

    try {
      const requestStart = performance.now();
      const formData = buildProcessFormData(originalFile, filter, kernelSize);

      const response = await fetch(`${API_BASE_URL}/v2/process`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error(await errorMessage(response));
      }

      const timings = parseServerTiming(response.headers.get("Server-Timing"));
      const requestTimeMs = performance.now() - requestStart;
      const executionTimeMs = timings.process ?? requestTimeMs;

      const imageBlob = await response.blob();
      const processedUrl = URL.createObjectURL(imageBlob);

      const bitmap = await createImageBitmap(imageBlob);
      const width = bitmap.width;
      const height = bitmap.height;
      bitmap.close();

      setResult({
        output_image: processedUrl,
        execution_time_ms: executionTimeMs,
        total_time_ms: timings.total ?? requestTimeMs,
        backend: response.headers.get("X-Processor-Backend") ?? "unknown",
        width,
        height,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      if (msg.includes("Failed to fetch") || msg.includes("NetworkError")) {
        setError(`Cannot reach the image service at ${API_BASE_URL}.`);
      } else {
        setError(msg);
      }
    } finally {
      setIsProcessing(false);
    }
  };

  const filterLabel: Record<FilterType, string> = {
    box_blur: "Box Blur",
    sobel_edge: "Sobel Edge Detection",
  };

  return (
    <div
      className="min-h-screen bg-background text-foreground"
      style={{ fontFamily: "'Inter', sans-serif" }}
    >
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-20 border-b border-[rgba(99,102,241,0.15)] bg-[#07090f]/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3.5">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-emerald-500/10 ring-1 ring-emerald-500/30">
              <Cpu size={16} className="text-emerald-400" />
            </div>
            <div>
              <h1 className="font-mono text-sm font-semibold tracking-tight text-foreground">
                HyperImage Studio
              </h1>
              <p className="font-mono text-[10px] text-muted-foreground tracking-widest uppercase">
                // Parallel Processing Dashboard
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="flex h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_6px_#10b981]" />
            <span className="font-mono text-xs text-muted-foreground">system online</span>
          </div>
        </div>
      </header>

      {/* ── Main grid ──────────────────────────────────────────────────────── */}
      <main className="mx-auto grid max-w-7xl gap-6 px-6 py-8 lg:grid-cols-[380px_1fr]">

        {/* ── Left panel: controls ──────────────────────────────────────────── */}
        <aside className="flex flex-col gap-5">

          {/* Upload zone */}
          <section className="rounded-xl border border-[rgba(99,102,241,0.15)] bg-card overflow-hidden">
            <div className="flex items-center gap-2 border-b border-[rgba(99,102,241,0.1)] px-4 py-2.5">
              <ImageIcon size={13} className="text-muted-foreground" />
              <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Input Image</span>
            </div>

            <div className="p-4">
              <div
                onDragEnter={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={onDrop}
                onClick={() => fileInputRef.current?.click()}
                className={[
                  "relative flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed cursor-pointer transition-all duration-200 min-h-[140px]",
                  isDragging
                    ? "border-emerald-400 bg-emerald-400/5 shadow-[0_0_20px_rgba(16,185,129,0.1)]"
                    : "border-[rgba(99,102,241,0.2)] hover:border-[rgba(99,102,241,0.4)] bg-[#090d17] hover:bg-[#0c1020]",
                ].join(" ")}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={onFileChange}
                />
                {originalURL ? (
                  <img
                    src={originalURL}
                    alt="Preview"
                    className="max-h-48 w-full object-contain rounded"
                  />
                ) : (
                  <>
                    <div className={`flex h-10 w-10 items-center justify-center rounded-full border ${isDragging ? "border-emerald-400/50 bg-emerald-400/10" : "border-[rgba(99,102,241,0.2)] bg-[#111827]"}`}>
                      <Upload size={18} className={isDragging ? "text-emerald-400" : "text-muted-foreground"} />
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-medium text-foreground">Drop image here</p>
                      <p className="font-mono text-xs text-muted-foreground mt-0.5">or click to browse</p>
                    </div>
                    <span className="font-mono text-[10px] uppercase tracking-widest text-[#3a4a5a]">PNG · JPEG · WebP</span>
                  </>
                )}
              </div>
              {originalFile && (
                <p className="mt-2 font-mono text-[11px] text-muted-foreground truncate">{originalFile.name} — {(originalFile.size / 1024).toFixed(1)} KB</p>
              )}
            </div>
          </section>

          {/* Controls */}
          <section className="rounded-xl border border-[rgba(99,102,241,0.15)] bg-card overflow-hidden">
            <div className="flex items-center gap-2 border-b border-[rgba(99,102,241,0.1)] px-4 py-2.5">
              <Layers size={13} className="text-muted-foreground" />
              <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Processing Parameters</span>
            </div>

            <div className="flex flex-col gap-5 p-4">
              {/* Filter select */}
              <div>
                <label className="mb-1.5 block font-mono text-xs text-muted-foreground uppercase tracking-wider">
                  Algorithm
                </label>
                <div className="relative">
                  <select
                    value={filter}
                    onChange={(e) => setFilter(e.target.value as FilterType)}
                    className="w-full appearance-none rounded-lg border border-[rgba(99,102,241,0.2)] bg-[#0b1019] px-3 py-2.5 font-mono text-sm text-foreground focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 cursor-pointer transition-colors hover:border-[rgba(99,102,241,0.4)]"
                  >
                    <option value="box_blur">Box Blur</option>
                    <option value="sobel_edge">Sobel Edge Detection</option>
                  </select>
                  <ChevronDown size={14} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                </div>
              </div>

              {/* Kernel slider */}
              {filter === "box_blur" && <div>
                <div className="mb-1.5 flex items-center justify-between">
                  <label className="font-mono text-xs text-muted-foreground uppercase tracking-wider">
                    Kernel Size
                  </label>
                  <span className="font-mono text-sm font-semibold text-emerald-400">
                    {kernelSize} × {kernelSize}
                  </span>
                </div>
                <input
                  type="range"
                  min={3}
                  max={21}
                  step={2}
                  value={kernelSize}
                  onChange={handleKernelChange}
                  className="w-full cursor-pointer accent-emerald-400"
                  style={{
                    accentColor: "#10b981",
                  }}
                />
                <div className="mt-1 flex justify-between font-mono text-[10px] text-[#3a4a5a]">
                  <span>3</span>
                  <span>21</span>
                </div>
              </div>}

              {/* Config summary */}
              <div className="rounded-md bg-[#080c14] border border-[rgba(99,102,241,0.08)] p-3 space-y-1.5">
                <TerminalLine label="filter" value={`"${filterLabel[filter]}"`} dim />
                {filter === "box_blur" && <TerminalLine label="kernel" value={`${kernelSize}x${kernelSize}`} dim />}
                <TerminalLine label="endpoint" value="/v2/process" dim />
              </div>

              {/* Process button */}
              <button
                onClick={processImage}
                disabled={!originalFile || isProcessing}
                className={[
                  "relative flex items-center justify-center gap-2.5 rounded-lg px-4 py-3 font-mono text-sm font-semibold transition-all duration-200",
                  !originalFile || isProcessing
                    ? "cursor-not-allowed bg-[#0e1827] text-[#3a4a5a] border border-[rgba(99,102,241,0.1)]"
                    : "cursor-pointer bg-emerald-500 text-black hover:bg-emerald-400 shadow-[0_0_20px_rgba(16,185,129,0.25)] hover:shadow-[0_0_30px_rgba(16,185,129,0.4)] active:scale-[0.98]",
                ].join(" ")}
              >
                {isProcessing ? (
                  <>
                    <Loader2 size={15} className="animate-spin" />
                    Processing…
                  </>
                ) : (
                  <>
                    <Zap size={15} />
                    Process Image
                  </>
                )}
              </button>

              {/* Error */}
              {error && (
                <div className="flex gap-2.5 rounded-lg border border-red-500/20 bg-red-500/5 p-3">
                  <AlertTriangle size={14} className="shrink-0 mt-0.5 text-red-400" />
                  <p className="font-mono text-xs text-red-400 leading-relaxed">{error}</p>
                </div>
              )}
            </div>
          </section>
        </aside>

        {/* ── Right panel: workspace + analytics ───────────────────────────── */}
        <div className="flex flex-col gap-5 min-w-0">

          {/* Comparison workspace */}
          <section className="rounded-xl border border-[rgba(99,102,241,0.15)] bg-card overflow-hidden">
            <div className="flex items-center gap-2 border-b border-[rgba(99,102,241,0.1)] px-4 py-2.5">
              <SplitSquareHorizontal size={13} className="text-muted-foreground" />
              <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Comparison Workspace</span>
              {result && (
                <span className="ml-auto font-mono text-[10px] text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full border border-emerald-400/20">
                  drag slider to compare
                </span>
              )}
            </div>

            <div className="p-4">
              {result && originalURL ? (
                <ComparisonSlider original={originalURL} processed={result.output_image} />
              ) : (
                <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-lg bg-[#080c14] border border-[rgba(99,102,241,0.08)]">
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[#0e1827] border border-[rgba(99,102,241,0.15)]">
                    <SplitSquareHorizontal size={20} className="text-[#3a4a5a]" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm text-muted-foreground">No output yet</p>
                    <p className="font-mono text-xs text-[#3a4a5a] mt-0.5">Upload an image and run processing</p>
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* Performance analytics */}
          <section className="rounded-xl border border-[rgba(99,102,241,0.15)] bg-card overflow-hidden">
            <div className="flex items-center gap-2 border-b border-[rgba(99,102,241,0.1)] px-4 py-2.5">
              <BarChart3 size={13} className="text-muted-foreground" />
              <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Performance Analytics</span>
              <span className="ml-auto font-mono text-[10px] uppercase tracking-widest text-[#3a4a5a]">sys/monitor</span>
            </div>

            <div className="p-4">
              {result ? (
                <div className="flex flex-col gap-5">
                  {/* Stat cards */}
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <StatCard
                      icon={Clock}
                      label="Exec Time"
                      value={`${result.execution_time_ms.toFixed(2)} ms`}
                      sub="native filter time"
                      color="bg-emerald-500"
                    />
                    <StatCard
                      icon={ImageIcon}
                      label="Resolution"
                      value={`${result.width} × ${result.height}`}
                      sub={`${(result.width * result.height / 1_000_000).toFixed(2)} megapixels`}
                      color="bg-indigo-500"
                    />
                    <StatCard
                      icon={Zap}
                      label="Throughput"
                      value={pixelsPerSec ? `${formatNumber(pixelsPerSec)} px/s` : "—"}
                      sub="pixels processed per second"
                      color="bg-amber-500"
                    />
                  </div>

                  {/* Terminal breakdown */}
                  <div className="rounded-lg bg-[#060a10] border border-[rgba(99,102,241,0.08)] p-4">
                    <div className="mb-3 flex items-center gap-2">
                      <span className="font-mono text-[10px] uppercase tracking-widest text-[#3a4a5a]">// execution report</span>
                    </div>
                    <div className="space-y-2">
                      <TerminalLine label="filter_applied" value={`"${filterLabel[filter]}"`} accent />
                      {filter === "box_blur" && <TerminalLine label="kernel_size" value={`${kernelSize}x${kernelSize}`} />}
                      <TerminalLine label="backend" value={result.backend} />
                      <TerminalLine label="image_width_px" value={result.width.toString()} />
                      <TerminalLine label="image_height_px" value={result.height.toString()} />
                      <TerminalLine label="total_pixels" value={formatNumber(result.width * result.height)} />
                      <TerminalLine label="execution_time_ms" value={`${result.execution_time_ms.toFixed(3)}`} accent />
                      <TerminalLine label="backend_total_ms" value={`${result.total_time_ms.toFixed(3)}`} />
                      {pixelsPerSec && (
                        <TerminalLine label="pixels_per_second" value={formatNumber(pixelsPerSec)} accent />
                      )}
                    </div>

                    {/* Timing bar */}
                    <div className="mt-4">
                      <div className="mb-1.5 flex justify-between font-mono text-[10px] text-[#3a4a5a]">
                        <span>execution_time</span>
                        <span>{result.execution_time_ms.toFixed(2)} ms</span>
                      </div>
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-[#0e1827]">
                        <div
                          className="h-full rounded-full bg-emerald-400 transition-all duration-700 shadow-[0_0_8px_#10b981]"
                          style={{
                            width: `${clamp((result.execution_time_ms / 2000) * 100, 2, 100)}%`,
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex h-40 flex-col items-center justify-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#0e1827] border border-[rgba(99,102,241,0.15)]">
                    <BarChart3 size={18} className="text-[#3a4a5a]" />
                  </div>
                  <p className="font-mono text-xs text-[#3a4a5a]">awaiting process run…</p>
                </div>
              )}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
