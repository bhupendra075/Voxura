import { useEffect, useRef, useState } from "react";
import { Enums as CoreEnums, RenderingEngine, eventTarget as cornerstoneEventTarget, init as initCore, type Types } from "@cornerstonejs/core";
import { init as initDicomImageLoader } from "@cornerstonejs/dicom-image-loader";
import {
  Enums as ToolEnums, LengthTool, PanTool, StackScrollTool, ToolGroupManager,
  WindowLevelTool, ZoomTool, addTool, annotation, init as initTools, utilities as toolUtilities,
} from "@cornerstonejs/tools";
import { clinicalApi, type Instance, type PresentationState } from "./clinicalApi";
import { buildDicomImageIds, dicomLoaderHeaders, orientationLabels, resolveVoiRange, viewerErrorMessage } from "./viewerPolicy";

export type ViewerTool = "window" | "pan" | "zoom" | "length";
export interface ViewportControls { reset: () => void; setIndex: (index: number) => void }
interface Props {
  instances: Instance[]; initialIndex: number; activeTool: ViewerTool; lengthEnabled: boolean;
  inverted: boolean; cine: boolean; onIndexChange: (index: number) => void;
  initialPresentation: PresentationState;
  onPresentationChange: (change: Partial<PresentationState>) => void;
  onError: (message: string) => void; onViewportReady?: (controls: ViewportControls | null) => void;
}

let initialization: Promise<void> | null = null;
let toolsRegistered = false;
async function initializeCornerstone() {
  if (!initialization) initialization = (async () => {
    initCore();
    initDicomImageLoader({
      maxWebWorkers: Math.max(1, Math.min(4, navigator.hardwareConcurrency || 1)),
      beforeSend: (_xhr, _imageId, defaultHeaders) => dicomLoaderHeaders(defaultHeaders, clinicalApi.authorizationHeaders()),
    });
    initTools();
    if (!toolsRegistered) {
      [WindowLevelTool, PanTool, ZoomTool, StackScrollTool, LengthTool].forEach(addTool);
      toolsRegistered = true;
    }
  })().catch((cause) => {
    initialization = null;
    throw cause;
  });
  return initialization;
}

export function ClinicalViewport({ instances, initialIndex, activeTool, lengthEnabled, inverted, cine, initialPresentation, onIndexChange, onPresentationChange, onError, onViewportReady }: Props) {
  const elementRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<Types.IStackViewport | null>(null);
  const engineRef = useRef<RenderingEngine | null>(null);
  const groupIdRef = useRef(`voxura-tools-${crypto.randomUUID()}`);
  const engineIdRef = useRef(`voxura-engine-${crypto.randomUUID()}`);
  const viewportIdRef = useRef(`voxura-viewport-${crypto.randomUUID()}`);
  const onIndexChangeRef = useRef(onIndexChange);
  const onPresentationChangeRef = useRef(onPresentationChange);
  const [loaded, setLoaded] = useState(false);
  const currentOrientation = orientationLabels(instances[Math.min(initialIndex, Math.max(0, instances.length - 1))]?.orientation);
  useEffect(() => { onIndexChangeRef.current = onIndexChange; }, [onIndexChange]);
  useEffect(() => { onPresentationChangeRef.current = onPresentationChange; }, [onPresentationChange]);

  useEffect(() => {
    const element = elementRef.current;
    if (!element || !instances.length) return;
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    const groupId = groupIdRef.current;
    const onNewImage = (event: Event) => {
      const detail = (event as CustomEvent<{ imageIdIndex?: number }>).detail;
      if (typeof detail?.imageIdIndex === "number") onIndexChangeRef.current(detail.imageIdIndex);
    };
    const emitViewportState = () => {
      const viewport = viewportRef.current;
      if (!viewport) return;
      const properties = viewport.getProperties();
      const pan = viewport.getPan();
      const voi = properties.voiRange;
      const lengths = lengthEnabled ? annotation.state.getAnnotations(LengthTool.toolName, element) : [];
      onPresentationChangeRef.current({
        window_center: voi ? (voi.lower + voi.upper) / 2 : null,
        window_width: voi ? voi.upper - voi.lower : null,
        zoom: viewport.getZoom(), pan_x: pan[0], pan_y: pan[1],
        annotations: structuredClone(lengths ?? []) as Array<Record<string, unknown>>,
      });
    };
    void initializeCornerstone().then(async () => {
      if (disposed) return;
      const engine = new RenderingEngine(engineIdRef.current);
      if (disposed) { engine.destroy(); return; }
      engineRef.current = engine;
      engine.enableElement({ viewportId: viewportIdRef.current, type: CoreEnums.ViewportType.STACK, element });
      const viewport = engine.getViewport(viewportIdRef.current) as Types.IStackViewport;
      viewportRef.current = viewport;
      const toolGroup = ToolGroupManager.createToolGroup(groupId);
      if (!toolGroup) throw new Error("Unable to create the clinical viewer tool group");
      [WindowLevelTool, PanTool, ZoomTool, StackScrollTool, LengthTool].forEach((tool) => toolGroup.addTool(tool.toolName));
      toolGroup.addViewport(viewportIdRef.current, engineIdRef.current);
      toolGroup.setToolActive(StackScrollTool.toolName, { bindings: [{ mouseButton: ToolEnums.MouseBindings.Wheel }] });
      toolGroup.setToolActive(ZoomTool.toolName, { bindings: [{ mouseButton: ToolEnums.MouseBindings.Secondary }] });
      element.addEventListener(CoreEnums.Events.STACK_NEW_IMAGE, onNewImage);
      const imageIds = buildDicomImageIds(instances, (id) => clinicalApi.dicomUrl(id));
      await viewport.setStack(imageIds, Math.min(initialIndex, imageIds.length - 1));
      if (disposed) return;
      const voiRange = resolveVoiRange(initialPresentation, instances[Math.min(initialIndex, instances.length - 1)]);
      viewport.setProperties({
        invert: inverted,
        ...(voiRange ? { voiRange } : {}),
      });
      viewport.setZoom(initialPresentation.zoom);
      viewport.setPan([initialPresentation.pan_x, initialPresentation.pan_y]);
      if (lengthEnabled) {
        initialPresentation.annotations.forEach((saved) => annotation.state.addAnnotation(
          structuredClone(saved) as Parameters<typeof annotation.state.addAnnotation>[0], element,
        ));
      }
      viewport.render();
      element.addEventListener(CoreEnums.Events.CAMERA_MODIFIED, emitViewportState);
      element.addEventListener(CoreEnums.Events.VOI_MODIFIED, emitViewportState);
      cornerstoneEventTarget.addEventListener(ToolEnums.Events.ANNOTATION_COMPLETED, emitViewportState);
      cornerstoneEventTarget.addEventListener(ToolEnums.Events.ANNOTATION_MODIFIED, emitViewportState);
      setLoaded(true);
      onViewportReady?.({
        reset: () => { viewport.resetCamera(); viewport.resetProperties(); viewport.render(); },
        setIndex: (index) => { void viewport.setImageIdIndex(Math.max(0, Math.min(imageIds.length - 1, index))); },
      });
      resizeObserver = new ResizeObserver(() => { if (!disposed && engineRef.current === engine) engine.resize(true, false); });
      resizeObserver.observe(element);
    }).catch((cause) => {
      if (disposed) return;
      element.removeEventListener(CoreEnums.Events.STACK_NEW_IMAGE, onNewImage);
      element.removeEventListener(CoreEnums.Events.CAMERA_MODIFIED, emitViewportState);
      element.removeEventListener(CoreEnums.Events.VOI_MODIFIED, emitViewportState);
      cornerstoneEventTarget.removeEventListener(ToolEnums.Events.ANNOTATION_COMPLETED, emitViewportState);
      cornerstoneEventTarget.removeEventListener(ToolEnums.Events.ANNOTATION_MODIFIED, emitViewportState);
      resizeObserver?.disconnect();
      toolUtilities.cine.stopClip(element);
      if (ToolGroupManager.getToolGroup(groupId)) ToolGroupManager.destroyToolGroup(groupId);
      engineRef.current?.destroy();
      engineRef.current = null; viewportRef.current = null;
      onViewportReady?.(null);
      onError(viewerErrorMessage(cause));
    });
    return () => {
      disposed = true; setLoaded(false); onViewportReady?.(null);
      element.removeEventListener(CoreEnums.Events.STACK_NEW_IMAGE, onNewImage);
      element.removeEventListener(CoreEnums.Events.CAMERA_MODIFIED, emitViewportState);
      element.removeEventListener(CoreEnums.Events.VOI_MODIFIED, emitViewportState);
      cornerstoneEventTarget.removeEventListener(ToolEnums.Events.ANNOTATION_COMPLETED, emitViewportState);
      cornerstoneEventTarget.removeEventListener(ToolEnums.Events.ANNOTATION_MODIFIED, emitViewportState);
      resizeObserver?.disconnect(); toolUtilities.cine.stopClip(element);
      if (ToolGroupManager.getToolGroup(groupId)) ToolGroupManager.destroyToolGroup(groupId);
      annotation.state.removeAnnotations(LengthTool.toolName, element);
      engineRef.current?.destroy();
      engineRef.current = null; viewportRef.current = null;
    };
    // A series change intentionally recreates the isolated viewport.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instances]);

  useEffect(() => {
    const toolGroup = ToolGroupManager.getToolGroup(groupIdRef.current);
    if (!toolGroup) return;
    [WindowLevelTool, PanTool, ZoomTool, LengthTool].forEach((tool) => toolGroup.setToolPassive(tool.toolName));
    const toolName = activeTool === "window" ? WindowLevelTool.toolName : activeTool === "pan" ? PanTool.toolName : activeTool === "zoom" ? ZoomTool.toolName : LengthTool.toolName;
    if (activeTool !== "length" || lengthEnabled) toolGroup.setToolActive(toolName, { bindings: [{ mouseButton: ToolEnums.MouseBindings.Primary }] });
  }, [activeTool, lengthEnabled, loaded]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.setProperties({ invert: inverted }); viewport.render();
  }, [inverted, loaded]);

  useEffect(() => {
    const element = elementRef.current;
    if (!element || !loaded) return;
    if (cine) toolUtilities.cine.playClip(element, { framesPerSecond: 8, loop: true });
    else toolUtilities.cine.stopClip(element);
    return () => toolUtilities.cine.stopClip(element);
  }, [cine, loaded]);

  return <div className="relative h-full w-full bg-black">
    <div ref={elementRef} role="img" tabIndex={0} aria-busy={!loaded} className="h-full w-full touch-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300" aria-label="Interactive DICOM stack viewport. Use the selected toolbar tool with the pointer; use arrow keys to change images." />
    {currentOrientation && <div aria-hidden="true" className="pointer-events-none absolute inset-0 text-xs font-semibold text-cyan-100 drop-shadow">
      <span className="absolute left-1/2 top-2 -translate-x-1/2">{currentOrientation.top}</span>
      <span className="absolute right-2 top-1/2 -translate-y-1/2">{currentOrientation.right}</span>
      <span className="absolute bottom-2 left-1/2 -translate-x-1/2">{currentOrientation.bottom}</span>
      <span className="absolute left-2 top-1/2 -translate-y-1/2">{currentOrientation.left}</span>
    </div>}
    {!loaded && <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-400">Loading source DICOM pixels…</div>}
  </div>;
}
