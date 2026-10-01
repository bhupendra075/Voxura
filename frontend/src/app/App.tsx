import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, ArrowLeft, BrainCircuit, CheckCircle2, ChevronLeft, ChevronRight, CircleUserRound,
  Contrast, Crosshair, FileImage, FolderOpen, Info, Loader2, Pause, Play,
  MonitorCheck, Move, RefreshCw, Ruler, Save, Search, ShieldCheck, Upload, ZoomIn,
} from "lucide-react";
import { ClinicalApiError, clinicalApi, isReviewChecklistComplete, type AiCapabilities, type AnalysisResults, type Instance, type PresentationState, type ReportDraft, type Series, type Study, type ViewerManifest } from "./clinicalApi";
import { ClinicalViewport, type ViewerTool, type ViewportControls } from "./ClinicalViewport";
import { isLengthMeasurementAvailable, partitionSupportedInstances, viewerBlockingReason } from "./viewerPolicy";

const defaultState: PresentationState = {
  version: 0,
  layout: "1x1", active_series_id: null, active_instance_id: null, frame: 0,
  window_center: null, window_width: null, zoom: 1, pan_x: 0, pan_y: 0,
  rotation: 0, inverted: false, annotations: [],
};
const emptyDraft: ReportDraft = { version: 0, status: "empty", findings_text: "", impression_text: "", updated_by: null, updated_at: null };
const emptyChecks = { patient_identity_confirmed: false, laterality_checked: false, priors_checked: false, critical_findings_checked: false, warnings_resolved: false };

function displayDate(value: string) {
  return value?.length === 8 ? `${value.slice(6, 8)} ${value.slice(4, 6)} ${value.slice(0, 4)}` : value || "—";
}

function Badge({ children, tone = "slate" }: { children: React.ReactNode; tone?: "slate" | "green" | "amber" | "red" }) {
  const colors = { slate: "border-slate-700 bg-slate-800 text-slate-200", green: "border-emerald-700 bg-emerald-950 text-emerald-300", amber: "border-amber-700 bg-amber-950 text-amber-300", red: "border-red-700 bg-red-950 text-red-300" };
  return <span className={`rounded border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${colors[tone]}`}>{children}</span>;
}

function EmptyViewer() {
  return <div className="flex h-full flex-col items-center justify-center gap-3 text-slate-500">
    <FileImage size={42} strokeWidth={1.25} />
    <div className="text-center"><p className="text-sm font-semibold text-slate-300">No study selected</p><p className="mt-1 text-xs">Choose a study from the worklist or import DICOM files.</p></div>
  </div>;
}

export default function App() {
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState("Radiologist");
  const [pacs, setPacs] = useState({ configured: false, reachable: false, message: "Checking PACS…" });
  const [studies, setStudies] = useState<Study[]>([]);
  const [query, setQuery] = useState("");
  const [selectedStudy, setSelectedStudy] = useState<Study | null>(null);
  const [series, setSeries] = useState<Series[]>([]);
  const [viewerManifest, setViewerManifest] = useState<ViewerManifest | null>(null);
  const [selectedSeries, setSelectedSeries] = useState<Series | null>(null);
  const [instances, setInstances] = useState<Instance[]>([]);
  const [instanceIndex, setInstanceIndex] = useState(0);
  const [frame, setFrame] = useState(0);
  const [presentation, setPresentation] = useState<PresentationState>(defaultState);
  const [report, setReport] = useState({ status: "unavailable", text: "No report is available for this study." });
  const [capabilities, setCapabilities] = useState<AiCapabilities | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResults>({ items: [], latest_job: null });
  const [draft, setDraft] = useState<ReportDraft>(emptyDraft);
  const [reviewChecks, setReviewChecks] = useState(emptyChecks);
  const [activeTool, setActiveTool] = useState<ViewerTool>("window");
  const [rightPanel, setRightPanel] = useState<"assist" | "report" | "details" | "measurements">("details");
  const [cine, setCine] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewerBlocker, setViewerBlocker] = useState<string | null>(null);
  const [importSummary, setImportSummary] = useState<{ accepted: number; rejected: number } | null>(null);
  const [showWorklist, setShowWorklist] = useState(true);
  const fileInput = useRef<HTMLInputElement>(null);
  const savedPresentation = useRef<PresentationState>(defaultState);
  const lastSavedPresentation = useRef("");
  const presentationSaveQueue = useRef(Promise.resolve());
  const currentStudyId = useRef<string | null>(null);
  const viewportControls = useRef<ViewportControls | null>(null);
  const studyLoadVersion = useRef(0);
  useEffect(() => { currentStudyId.current = selectedStudy?.id ?? null; }, [selectedStudy]);

  const refreshStudies = useCallback(async (search = query) => {
    const response = await clinicalApi.studies(search);
    setStudies(response.items);
  }, [query]);

  useEffect(() => {
    void (async () => {
      try {
        const session = await clinicalApi.ensureDevelopmentSession();
        setUser(session.display_name);
        const [health, ai] = await Promise.all([clinicalApi.pacsHealth(), clinicalApi.aiCapabilities(), refreshStudies("")]);
        setPacs(health);
        setCapabilities(ai);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Clinical service is unavailable");
      } finally { setReady(true); }
    })();
  }, [refreshStudies]);

  useEffect(() => {
    const handleSessionExpired = (event: Event) => {
      const message = (event as CustomEvent<{ message?: string }>).detail?.message;
      studyLoadVersion.current += 1;
      viewportControls.current = null;
      setSelectedStudy(null); setSelectedSeries(null); setSeries([]); setViewerManifest(null);
      setInstances([]); setInstanceIndex(0); setFrame(0); setCine(false); setViewerBlocker(null);
      setShowWorklist(true); setError(message || "Your session expired. Sign in again before viewing clinical data.");
    };
    window.addEventListener("voxura:session-expired", handleSessionExpired);
    return () => window.removeEventListener("voxura:session-expired", handleSessionExpired);
  }, []);

  useEffect(() => {
    if (!selectedStudy) return;
    const version = ++studyLoadVersion.current;
    let cancelled = false;
    setBusy(true); setError(null); setViewerBlocker(null); setSelectedSeries(null); setSeries([]);
    setViewerManifest(null); setInstances([]); setInstanceIndex(0); setFrame(0); setCine(false);
    viewportControls.current = null;
    void Promise.all([clinicalApi.series(selectedStudy.id), clinicalApi.viewerManifest(selectedStudy.id), clinicalApi.report(selectedStudy.id), clinicalApi.presentation(selectedStudy.id), clinicalApi.analysisResults(selectedStudy.id), clinicalApi.reportDraft(selectedStudy.id)])
      .then(([seriesResponse, manifest, reportResponse, saved, analysisResponse, draftResponse]) => {
        if (cancelled || version !== studyLoadVersion.current) return;
        // Multi-series viewport assignment is not implemented yet. Always open the
        // diagnostic source in one reliable viewport rather than retaining a saved
        // layout with empty or misleading panes.
        const safePresentation = { ...saved, layout: "1x1" as const };
        savedPresentation.current = safePresentation;
        lastSavedPresentation.current = JSON.stringify({ ...safePresentation, version: 0 });
        const enrichedSeries = seriesResponse.items.map((item) => {
          const manifestSeries = manifest.series.find((candidate) => candidate.id === item.id);
          return manifestSeries ? { ...item, has_pixel_spacing: manifestSeries.has_pixel_spacing, warnings: manifestSeries.warnings } : item;
        });
        setSeries(enrichedSeries); setViewerManifest(manifest); setReport(reportResponse); setPresentation(safePresentation); setAnalysis(analysisResponse); setDraft(draftResponse); setReviewChecks(emptyChecks);
        const initial = enrichedSeries.find((item) => item.id === safePresentation.active_series_id) ?? enrichedSeries[0] ?? null;
        setSelectedSeries(initial); setShowWorklist(false);
      }).catch((cause) => { if (!cancelled && version === studyLoadVersion.current) setError(cause instanceof Error ? cause.message : "Unable to open study"); })
      .finally(() => { if (!cancelled && version === studyLoadVersion.current) setBusy(false); });
    return () => { cancelled = true; };
  }, [selectedStudy]);

  useEffect(() => {
    let cancelled = false;
    setInstances([]); setInstanceIndex(0); setFrame(0); setCine(false); setError(null); setViewerBlocker(null);
    viewportControls.current = null;
    if (!selectedStudy || !selectedSeries) return;
    setBusy(true);
    const manifestSeries = viewerManifest?.series.find((item) => item.id === selectedSeries.id);
    if (!manifestSeries) { setError("Viewer manifest is unavailable for this series"); setBusy(false); return; }
    Promise.resolve(manifestSeries).then((metadata) => {
      if (cancelled) return;
      const blockingReason = viewerBlockingReason(metadata.instances, metadata.complete, metadata.warnings);
      if (blockingReason) { setViewerBlocker(blockingReason); setInstances([]); return; }
      const { supported, rejected } = partitionSupportedInstances(metadata.instances);
      const omitted = rejected.length;
      if (omitted) setError(`${omitted} instance${omitted === 1 ? " was" : "s were"} excluded: the controlled pilot supports only validated uncompressed, single-frame DICOM objects.`);
      setInstances(supported);
      const savedIndex = Math.max(0, supported.findIndex((item) => item.id === savedPresentation.current.active_instance_id));
      setInstanceIndex(savedIndex); setFrame(savedIndex >= 0 ? savedPresentation.current.frame : 0);
    }).catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "Unable to load series"); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [selectedStudy, selectedSeries, viewerManifest]);

  const currentInstance = instances[instanceIndex] ?? null;
  const activeToolLabel = { window: "Window and level", pan: "Pan", zoom: "Zoom", length: "Length measurement" }[activeTool];

  useEffect(() => {
    if (activeTool === "length" && !isLengthMeasurementAvailable(selectedSeries?.has_pixel_spacing)) setActiveTool("window");
  }, [activeTool, selectedSeries]);

  useEffect(() => {
    if (!selectedStudy || !selectedSeries || !currentInstance) return;
    const next = { ...presentation, version: savedPresentation.current.version, active_series_id: selectedSeries.id, active_instance_id: currentInstance.id, frame };
    const fingerprint = JSON.stringify({ ...next, version: 0 });
    if (fingerprint === lastSavedPresentation.current) return;
    const studyId = selectedStudy.id;
    const timer = window.setTimeout(() => {
      presentationSaveQueue.current = presentationSaveQueue.current.then(async () => {
        const stateToSave = { ...next, version: savedPresentation.current.version };
        try {
          const saved = await clinicalApi.savePresentation(studyId, stateToSave);
          if (currentStudyId.current !== studyId) return;
          savedPresentation.current = saved;
          lastSavedPresentation.current = JSON.stringify({ ...saved, version: 0 });
          setPresentation((current) => ({ ...current, version: saved.version }));
        } catch (cause) {
          if (cause instanceof ClinicalApiError && cause.status === 409) {
            const latest = await clinicalApi.presentation(studyId);
            if (currentStudyId.current !== studyId) return;
            savedPresentation.current = latest; lastSavedPresentation.current = JSON.stringify({ ...latest, version: 0 });
            setPresentation(latest); setError("Viewer state changed in another session. The latest saved state was restored.");
          } else if (currentStudyId.current === studyId) setError(cause instanceof Error ? cause.message : "Unable to save viewer state");
        }
      });
    }, 600);
    return () => window.clearTimeout(timer);
  }, [selectedStudy, selectedSeries, currentInstance, frame, presentation]);

  const goSlice = useCallback((delta: number) => {
    if (!currentInstance) return;
    if (currentInstance.frame_count > 1) setFrame((value) => Math.min(currentInstance.frame_count - 1, Math.max(0, value + delta)));
    else setInstanceIndex((value) => {
      const next = Math.min(instances.length - 1, Math.max(0, value + delta));
      viewportControls.current?.setIndex(next);
      return next;
    });
  }, [currentInstance, instances.length]);

  const handleImport = async (files: File[]) => {
    if (!files.length) return;
    setBusy(true); setError(null); setImportSummary(null);
    try {
      const result = await clinicalApi.import(files);
      setImportSummary({ accepted: result.accepted.length, rejected: result.rejected.length });
      if (result.rejected.length) {
        const prefix = result.accepted.length ? "Some files were not imported." : "No files were imported.";
        setError(`${prefix} ${result.rejected.slice(0, 2).map((item) => `${item.filename}: ${item.reason}`).join(" · ")}`);
      }
      await refreshStudies("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Import failed"); }
    finally { setBusy(false); }
  };

  const updatePresentation = (change: Partial<PresentationState>) => setPresentation((value) => ({ ...value, ...change }));
  const runAnalysis = async () => {
    if (!selectedStudy) return;
    setBusy(true); setError(null);
    try {
      const latest_job = await clinicalApi.createAnalysis(selectedStudy.id);
      setAnalysis((value) => ({ ...value, latest_job }));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to qualify study"); }
    finally { setBusy(false); }
  };
  const saveDraft = async () => {
    if (!selectedStudy) return;
    setBusy(true); setError(null);
    try { setDraft(await clinicalApi.saveReportDraft(selectedStudy.id, draft)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to save draft"); }
    finally { setBusy(false); }
  };
  const reviewDraft = async () => {
    if (!selectedStudy) return;
    setBusy(true); setError(null);
    try { setDraft(await clinicalApi.reviewReportDraft(selectedStudy.id, draft.version, reviewChecks)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to mark draft reviewed"); }
    finally { setBusy(false); }
  };
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!selectedStudy || event.altKey || event.ctrlKey || event.metaKey || ["INPUT", "TEXTAREA", "SELECT"].includes((event.target as HTMLElement)?.tagName)) return;
      if (event.key === "ArrowLeft" || event.key === "ArrowDown") { event.preventDefault(); goSlice(-1); }
      if (event.key === "ArrowRight" || event.key === "ArrowUp") { event.preventDefault(); goSlice(1); }
      if (event.key.toLowerCase() === "p") setActiveTool("pan");
      if (event.key.toLowerCase() === "w") setActiveTool("window");
      if (event.key === "0") { viewportControls.current?.reset(); updatePresentation({ inverted: false }); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedStudy, selectedSeries, currentInstance, goSlice]);

  if (!ready) return <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-200"><Loader2 className="mr-3 animate-spin" /> Initializing secure viewer…</div>;

  return <div className="flex h-screen flex-col overflow-hidden bg-[#070a0e] text-slate-100">
    <header className="flex h-14 shrink-0 items-center border-b border-slate-800 bg-[#0b1016] px-4">
      <div className="flex items-center gap-3"><div className="rounded bg-cyan-500/15 p-1.5 text-cyan-300"><Crosshair size={20} /></div><div><h1 className="text-sm font-bold tracking-wide">Voxura</h1><p className="text-[10px] uppercase tracking-[.16em] text-slate-500">Clinical visualization aid · Not autonomous diagnosis</p></div></div>
      <div className="ml-auto flex items-center gap-3">
        <div className={`flex items-center gap-2 rounded border px-2.5 py-1 text-xs ${pacs.reachable ? "border-emerald-800 bg-emerald-950/50 text-emerald-300" : "border-amber-900 bg-amber-950/40 text-amber-300"}`}><span className={`h-1.5 w-1.5 rounded-full ${pacs.reachable ? "bg-emerald-400" : "bg-amber-400"}`} />{pacs.message}</div>
        <div className="flex items-center gap-2 text-xs text-slate-300"><CircleUserRound size={17} /><span>{user}</span><Badge>Radiologist</Badge></div>
      </div>
    </header>

    {selectedStudy && <div aria-label="Patient safety banner" className="flex h-12 shrink-0 items-center gap-5 border-b border-cyan-950 bg-[#0d151d] px-4 text-xs">
      <button onClick={() => setShowWorklist(true)} className="flex items-center gap-1.5 rounded px-2 py-1.5 text-slate-300 hover:bg-slate-800"><ArrowLeft size={15} /> Worklist</button>
      <div><span className="text-slate-500">Patient</span><strong className="ml-2 text-sm text-white">{selectedStudy.patient_name}</strong></div>
      <div><span className="text-slate-500">ID</span><strong className="ml-2">{selectedStudy.patient_id}</strong></div>
      <div><span className="text-slate-500">DOB</span><strong className="ml-2">{displayDate(selectedStudy.birth_date)}</strong></div>
      <div><span className="text-slate-500">Accession</span><strong className="ml-2">{selectedStudy.accession || "—"}</strong></div>
      <div><span className="text-slate-500">Study</span><strong className="ml-2">{displayDate(selectedStudy.study_date)}</strong></div>
      <Badge tone="green">{selectedStudy.modalities.replaceAll("\\", " · ")}</Badge>
      <div className="ml-auto flex items-center gap-3"><div className="flex items-center gap-1.5 text-amber-200"><AlertTriangle size={15} /> Confirm patient and laterality</div><div className="flex items-center gap-1.5 text-emerald-300"><ShieldCheck size={15} /> Source pixels immutable</div></div>
    </div>}

    {error && <div role="alert" className="flex shrink-0 items-center gap-2 border-b border-red-900 bg-red-950/80 px-4 py-2 text-xs text-red-200"><AlertTriangle size={15} /><span className="flex-1">{error}</span><button onClick={() => setError(null)} className="underline">Dismiss</button></div>}

    <main className="min-h-0 flex-1">
      {showWorklist || !selectedStudy ? <section className="h-full overflow-auto bg-slate-100 text-slate-950">
        <div className="mx-auto max-w-7xl p-6">
          <div className="mb-6 flex items-end justify-between"><div><h2 className="text-2xl font-semibold">Imaging worklist</h2><p className="mt-1 text-sm text-slate-600">Search local studies or connect an institutional DICOMweb archive.</p></div><div className="flex gap-2"><input ref={fileInput} type="file" accept=".dcm,application/dicom" multiple className="hidden" onChange={(event) => void handleImport(Array.from(event.target.files ?? []))} /><button onClick={() => fileInput.current?.click()} className="flex items-center gap-2 rounded bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700"><Upload size={16} /> Import DICOM</button></div></div>
          <div className="mb-2 flex items-center justify-between text-xs text-slate-500"><span>Search only within your institution.</span><span>{studies.length} study{studies.length === 1 ? "" : "ies"} shown</span></div>
          <div className="mb-4 grid gap-3 rounded-lg border border-slate-300 bg-white p-3 shadow-sm sm:grid-cols-[1fr_auto_auto]"><label className="relative"><Search className="absolute left-3 top-2.5 text-slate-400" size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void refreshStudies(); }} placeholder="Search patient name or ID" aria-label="Search patient name or identifier" className="w-full rounded border border-slate-300 py-2 pl-10 pr-3 text-sm outline-none focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100" /></label><button onClick={() => void refreshStudies()} className="rounded border border-slate-300 px-4 py-2 text-sm font-semibold hover:bg-slate-50">Search</button><button onClick={() => { setQuery(""); void refreshStudies(""); }} aria-label="Clear search and refresh worklist" className="rounded border border-slate-300 px-3 hover:bg-slate-50"><RefreshCw size={16} /></button></div>
          {importSummary && <div role="status" className={`mb-4 flex items-center gap-2 rounded border px-3 py-2 text-sm ${importSummary.rejected ? "border-amber-300 bg-amber-50 text-amber-900" : "border-emerald-300 bg-emerald-50 text-emerald-800"}`}><CheckCircle2 size={16} /> Import finished: {importSummary.accepted} imported · {importSummary.rejected} rejected{importSummary.rejected ? ". Review the message above for file-specific reasons." : ""}</div>}
          <div className="overflow-hidden rounded-lg border border-slate-300 bg-white shadow-sm">
            <table className="w-full text-left text-sm"><thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-300"><tr><th className="px-4 py-3">Patient</th><th>Study</th><th>Accession</th><th>Modality</th><th>Status</th><th className="pr-4 text-right">Open</th></tr></thead><tbody className="divide-y divide-slate-200">{studies.map((study) => <tr key={study.id} className="hover:bg-cyan-50"><td className="px-4 py-3"><strong className="block">{study.patient_name}</strong><span className="text-xs text-slate-500">{study.patient_id} · DOB {displayDate(study.birth_date)}</span></td><td><strong className="block font-medium">{study.description}</strong><span className="text-xs text-slate-500">{displayDate(study.study_date)}</span></td><td>{study.accession || "—"}</td><td><Badge>{study.modalities.replaceAll("\\", " · ")}</Badge></td><td><Badge tone={study.status === "unread" ? "amber" : "green"}>{study.status}</Badge></td><td className="pr-4 text-right"><button onClick={() => setSelectedStudy(study)} className="rounded bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-600">Review study</button></td></tr>)}</tbody></table>
            {!studies.length && <div className="flex flex-col items-center gap-3 p-16 text-slate-500"><FolderOpen size={36} /><p className="font-semibold text-slate-700">No studies in this worklist</p><p className="text-sm">Import de-identified CR, DX, CT, or MR DICOM files to begin.</p></div>}
          </div>
          <div className="mt-4 flex items-start gap-2 rounded border border-blue-200 bg-blue-50 p-3 text-xs text-blue-900"><Info size={16} className="mt-0.5 shrink-0" /> Clinical use requires institutional authorization, validated displays, security controls, and regional regulatory approval. Use de-identified studies during development.</div>
        </div>
      </section> : <section className="grid h-full min-h-0 grid-cols-[190px_minmax(0,1fr)_360px]">
        <aside className="overflow-y-auto border-r border-slate-800 bg-[#0b1016] p-2"><p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[.16em] text-slate-500">Series · {series.length}</p>{series.map((item) => <button key={item.id} onClick={() => setSelectedSeries(item)} className={`mb-2 w-full overflow-hidden rounded border text-left ${selectedSeries?.id === item.id ? "border-cyan-500 bg-cyan-950/30" : "border-slate-800 bg-slate-900 hover:border-slate-600"}`}><div className="flex h-20 items-center justify-center bg-black text-slate-600"><FileImage size={26} /><span className="ml-2 text-xs">{item.modality}</span></div><div className="p-2"><p className="truncate text-xs font-semibold text-slate-200">{item.series_number ?? "—"}. {item.description}</p><p className="mt-1 text-[10px] text-slate-500">{item.instance_count} instances · {item.frame_count} frames</p></div></button>)}</aside>

        <div className="flex min-w-0 flex-col bg-black">
          <div className="flex h-12 shrink-0 items-center gap-1 border-b border-slate-800 bg-[#0b1016] px-2">
            {([ ["window", MonitorCheck, "W/L"], ["pan", Move, "Pan"], ["zoom", ZoomIn, "Zoom"], ["length", Ruler, "Length"] ] as const).map(([tool, Icon, label]) => {
              const available = !busy && !viewerBlocker && !!currentInstance && (tool !== "length" || isLengthMeasurementAvailable(selectedSeries?.has_pixel_spacing));
              const unavailableReason = viewerBlocker || (!currentInstance ? "No validated image is loaded" : "Length requires valid DICOM pixel spacing");
              return <button key={tool} title={available ? `${label} tool` : unavailableReason} aria-label={`${label} tool${available ? "" : ` unavailable: ${unavailableReason}`}`} aria-pressed={available && activeTool === tool} disabled={!available} onClick={() => setActiveTool(tool)} className={`flex h-9 items-center gap-1.5 rounded px-2.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${available && activeTool === tool ? "bg-cyan-700 text-white" : "text-slate-400 hover:bg-slate-800"} disabled:cursor-not-allowed disabled:opacity-40`}><Icon size={15} />{label}</button>;
            })}
            <span className="mx-1 h-6 w-px bg-slate-700" />
            <button title="Invert grayscale" aria-label="Invert grayscale" aria-pressed={presentation.inverted} disabled={busy || !!viewerBlocker || !currentInstance} onClick={() => updatePresentation({ inverted: !presentation.inverted })} className={`rounded p-2 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-not-allowed disabled:opacity-40 ${presentation.inverted ? "bg-slate-700" : ""}`}><Contrast size={16} /></button>
            <button title={cine ? "Stop cine" : "Start cine"} aria-label={cine ? "Stop cine playback" : "Start cine playback"} aria-pressed={cine} disabled={busy || !!viewerBlocker || instances.length < 2} onClick={() => setCine((value) => !value)} className={`flex h-9 items-center gap-1.5 rounded px-2.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-not-allowed disabled:opacity-40 ${cine ? "bg-cyan-700" : "hover:bg-slate-800"}`}>{cine ? <Pause size={15} /> : <Play size={15} />} Cine</button>
            <button title="Reset viewer (0)" disabled={busy || !!viewerBlocker || !currentInstance} onClick={() => { viewportControls.current?.reset(); updatePresentation({ inverted: false }); }} className="rounded px-2 py-1.5 text-xs text-slate-300 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-not-allowed disabled:opacity-40">Reset</button>
            <div className="ml-auto text-[10px] uppercase tracking-wide text-slate-500">Single source-DICOM viewport</div>
          </div>
          <div aria-label={`Viewer. ${activeToolLabel} selected. Arrow keys scroll images; W selects windowing, P selects pan, and 0 resets.`} className="relative min-h-0 flex-1 overflow-hidden bg-black ring-1 ring-inset ring-cyan-700">
            {instances.length ? <ClinicalViewport key={`${selectedStudy.id}:${selectedSeries?.id ?? "none"}`} instances={instances} initialIndex={instanceIndex} activeTool={activeTool} lengthEnabled={isLengthMeasurementAvailable(selectedSeries?.has_pixel_spacing)} inverted={presentation.inverted} cine={cine} initialPresentation={presentation} onPresentationChange={updatePresentation} onIndexChange={setInstanceIndex} onError={setError} onViewportReady={(controls) => { viewportControls.current = controls; }} /> : <EmptyViewer />}
            {viewerBlocker && <div role="alert" aria-live="assertive" className="absolute inset-0 z-20 flex items-center justify-center bg-black/95 p-8"><div className="max-w-lg rounded border border-red-700 bg-red-950 p-5 text-center text-red-100"><AlertTriangle className="mx-auto mb-3" size={30} /><h2 className="font-semibold">Series cannot be displayed safely</h2><p className="mt-2 text-sm leading-6">{viewerBlocker}</p><p className="mt-3 text-xs text-red-200">Choose another validated series. This warning cannot be dismissed.</p></div></div>}
            <div className="pointer-events-none absolute left-3 top-3 text-[11px] leading-5 text-cyan-200 drop-shadow"><p>{selectedSeries?.modality} · {selectedSeries?.description}</p><p>{selectedSeries?.rows ?? "—"} × {selectedSeries?.columns ?? "—"}</p></div>
            <div className="pointer-events-none absolute right-3 top-3 text-right text-[11px] leading-5 text-slate-300"><p>{selectedStudy.patient_name}</p><p>{selectedStudy.patient_id}</p></div>
            <div className="pointer-events-none absolute bottom-3 left-3 text-[11px] text-slate-300"><p>{selectedSeries?.has_pixel_spacing ? "Calibrated spacing available" : "Uncalibrated — measurement disabled"}</p><p>{activeToolLabel}</p></div>
            <div className="pointer-events-none absolute bottom-3 right-3 text-[11px] text-slate-300">Image {instanceIndex + 1}/{instances.length || 0}</div>
          </div>
          <div className="flex h-11 shrink-0 items-center border-t border-slate-800 bg-[#0b1016] px-3"><button aria-label="Previous image" onClick={() => goSlice(-1)} disabled={!currentInstance || instanceIndex === 0} className="rounded p-1.5 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:opacity-30"><ChevronLeft size={18} /></button><input aria-label={`Current image ${instances.length ? instanceIndex + 1 : 0} of ${instances.length}`} disabled={!currentInstance || !!viewerBlocker} type="range" min={0} max={Math.max(0, instances.length - 1)} value={instanceIndex} onChange={(event) => { const next = Number(event.target.value); setInstanceIndex(next); viewportControls.current?.setIndex(next); }} className="mx-3 flex-1 accent-cyan-500 disabled:opacity-40" /><button aria-label="Next image" onClick={() => goSlice(1)} disabled={!currentInstance || instanceIndex >= instances.length - 1} className="rounded p-1.5 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:opacity-30"><ChevronRight size={18} /></button><span aria-live="polite" className="ml-3 min-w-24 text-right text-xs text-slate-400">{instances.length} images</span></div>
        </div>

        <aside aria-label="Study context" className="min-h-0 border-l border-slate-800 bg-[#0b1016]"><div role="tablist" aria-label="Study context sections" className="flex h-11 border-b border-slate-800">{(["details", "report", "measurements"] as const).map((tab) => <button role="tab" aria-selected={rightPanel === tab} key={tab} onClick={() => setRightPanel(tab)} className={`flex-1 text-[10px] font-semibold uppercase tracking-wide focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300 ${rightPanel === tab ? "border-b-2 border-cyan-500 text-cyan-300" : "text-slate-500 hover:text-slate-300"}`}>{tab}</button>)}</div><div role="tabpanel" className="h-[calc(100%-44px)] overflow-y-auto p-4 text-sm">
          {rightPanel === "assist" && <div className="space-y-4">
            <div className="flex items-center justify-between"><div className="flex items-center gap-2"><BrainCircuit size={18} className="text-cyan-300" /><h3 className="font-semibold">AI Assist</h3></div><Badge tone="amber">Not diagnostic</Badge></div>
            <p className="text-xs leading-5 text-slate-400">Evidence-linked radiologist assistance only. Results never sign or finalize a report.</p>
            <div className={`rounded border p-3 ${analysis.latest_job?.state === "abstained" ? "border-amber-900 bg-amber-950/30" : "border-slate-700 bg-slate-900"}`}>
              <div className="flex items-center justify-between"><p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Study readiness</p>{analysis.latest_job && <Badge tone={analysis.latest_job.state === "completed" ? "green" : analysis.latest_job.state === "failed" ? "red" : "amber"}>{analysis.latest_job.state}</Badge>}</div>
              {analysis.latest_job ? <><p className="mt-2 text-xs leading-5 text-slate-300">{analysis.latest_job.message}</p><div className="mt-2 flex flex-wrap gap-1">{analysis.latest_job.manifest.sequences.length ? analysis.latest_job.manifest.sequences.map((sequence) => <Badge key={sequence}>{sequence}</Badge>) : <span className="text-xs text-amber-300">No MRI sequences identified from metadata</span>}</div>{analysis.latest_job.manifest.warnings.map((warning) => <p key={warning} className="mt-2 text-[11px] leading-4 text-amber-300">{warning}</p>)}</> : <p className="mt-2 text-xs text-slate-400">Run qualification to check modality, sequences, and enabled validated modules.</p>}
              <button onClick={() => void runAnalysis()} className="mt-3 w-full rounded bg-cyan-700 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-600">Qualify study for analysis</button>
            </div>
            <div className="rounded border border-slate-800 bg-slate-900 p-3"><p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Validated coverage</p><div className="mt-2 space-y-2">{capabilities?.models.map((model) => <div key={model.id} className="border-t border-slate-800 pt-2 first:border-0 first:pt-0"><div className="flex items-start justify-between gap-2"><p className="text-xs font-medium text-slate-200">{model.display_name}</p><Badge tone={model.enabled ? "green" : "slate"}>{model.enabled ? "enabled" : model.status}</Badge></div><p className="mt-1 text-[11px] leading-4 text-slate-500">{model.intended_use}</p></div>)}</div></div>
            <div className="rounded border border-slate-800 p-3"><div className="flex items-center justify-between"><p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Proposed findings</p><span className="text-xs text-slate-500">{analysis.items.length}</span></div>{analysis.items.length ? <p className="mt-2 text-xs text-slate-300">Evidence results are available for clinician review.</p> : <div className="mt-2 rounded bg-slate-900 p-3 text-xs leading-5 text-slate-400">No validated model findings are available. This does <strong className="text-amber-300">not</strong> mean the study is normal.</div>}</div>
            <div className="space-y-3 rounded border border-slate-800 p-3"><div className="flex items-center justify-between"><p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Clinician draft</p><Badge tone={draft.status === "reviewed" ? "green" : draft.status === "draft" ? "amber" : "slate"}>{draft.status}</Badge></div><label className="block text-[11px] uppercase tracking-wide text-slate-500">Findings<textarea value={draft.findings_text} onChange={(event) => setDraft((value) => ({ ...value, findings_text: event.target.value, status: "draft" }))} rows={6} className="mt-1 w-full resize-y rounded border border-slate-700 bg-slate-950 p-2 text-xs normal-case tracking-normal text-slate-200 outline-none focus:border-cyan-600" placeholder="Enter reviewed, evidence-linked findings…" /></label><label className="block text-[11px] uppercase tracking-wide text-slate-500">Impression<textarea value={draft.impression_text} onChange={(event) => setDraft((value) => ({ ...value, impression_text: event.target.value, status: "draft" }))} rows={4} className="mt-1 w-full resize-y rounded border border-slate-700 bg-slate-950 p-2 text-xs normal-case tracking-normal text-slate-200 outline-none focus:border-cyan-600" placeholder="Enter a radiologist-reviewed impression…" /></label><button onClick={() => void saveDraft()} className="flex w-full items-center justify-center gap-2 rounded border border-cyan-800 px-3 py-2 text-xs font-semibold text-cyan-200 hover:bg-cyan-950"><Save size={14} />Save versioned draft</button></div>
            {draft.version > 0 && draft.status !== "reviewed" && <div className="rounded border border-amber-900 bg-amber-950/20 p-3"><p className="text-xs font-semibold text-amber-200">Radiologist safety review</p><div className="mt-2 space-y-2">{([ ["patient_identity_confirmed", "Patient identity confirmed"], ["laterality_checked", "Laterality checked"], ["priors_checked", "Priors checked or unavailable"], ["critical_findings_checked", "Critical findings checked"], ["warnings_resolved", "Warnings resolved"] ] as const).map(([key, label]) => <label key={key} className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={reviewChecks[key]} onChange={(event) => setReviewChecks((value) => ({ ...value, [key]: event.target.checked }))} className="accent-cyan-500" />{label}</label>)}</div><button disabled={!isReviewChecklistComplete(reviewChecks)} onClick={() => void reviewDraft()} className="mt-3 w-full rounded bg-emerald-800 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40">Mark reviewed — not signed</button></div>}
          </div>}
          {rightPanel === "report" && <><div className="mb-4 flex items-center justify-between"><h3 className="font-semibold">Radiology report</h3><Badge tone={report.status === "final" ? "green" : "slate"}>{report.status}</Badge></div><div className="whitespace-pre-wrap rounded border border-slate-800 bg-slate-900 p-3 text-sm leading-6 text-slate-300">{report.text}</div><p className="mt-3 text-xs text-slate-500">Read-only report context. This viewer does not generate findings.</p></>}
          {rightPanel === "details" && <div className="space-y-4"><h3 className="font-semibold">Study details</h3>{[["Description", selectedStudy.description], ["Study date", displayDate(selectedStudy.study_date)], ["Accession", selectedStudy.accession || "—"], ["Modality", selectedStudy.modalities], ["Series", selectedSeries?.description ?? "—"], ["Laterality", selectedSeries?.laterality || "—"], ["Transfer syntax", currentInstance?.transfer_syntax || "—"]].map(([label, value]) => <div key={label} className="border-b border-slate-800 pb-2"><p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p><p className="mt-1 break-words text-slate-200">{value}</p></div>)}</div>}
          {rightPanel === "measurements" && <div><h3 className="mb-4 font-semibold">Measurements</h3><div className="rounded border border-dashed border-slate-700 p-6 text-center text-xs text-slate-500"><Ruler className="mx-auto mb-2" size={24} />{presentation.annotations.length ? `${presentation.annotations.length} saved calibrated length measurement${presentation.annotations.length === 1 ? "" : "s"}.` : "No saved measurements."}<br />{presentation.annotations.length ? "Measurements restore with this study." : "Select the calibrated length tool to begin."}</div><div className="mt-4 rounded border border-amber-900 bg-amber-950/30 p-3 text-xs text-amber-200"><AlertTriangle className="mr-2 inline" size={14} />Measurements require valid pixel spacing metadata.</div></div>}
        </div></aside>
      </section>}
    </main>
    {busy && <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-black/25"><div className="flex items-center gap-2 rounded bg-slate-900 px-4 py-3 text-sm shadow-xl"><Loader2 className="animate-spin text-cyan-400" size={18} /> Loading clinical data…</div></div>}
  </div>;
}
