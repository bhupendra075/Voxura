import type { Instance } from "./clinicalApi";

export const VALIDATED_UNCOMPRESSED_TRANSFER_SYNTAXES = new Set([
  "1.2.840.10008.1.2",
  "1.2.840.10008.1.2.1",
  "1.2.840.10008.1.2.2",
]);

export function partitionSupportedInstances(instances: Instance[]) {
  const supported: Instance[] = [];
  const rejected: Array<{ instance: Instance; reason: "multi-frame" | "unsupported-transfer-syntax" }> = [];
  for (const instance of instances) {
    if (instance.frame_count !== 1) rejected.push({ instance, reason: "multi-frame" });
    else if (!VALIDATED_UNCOMPRESSED_TRANSFER_SYNTAXES.has(instance.transfer_syntax)) {
      rejected.push({ instance, reason: "unsupported-transfer-syntax" });
    } else supported.push(instance);
  }
  return { supported, rejected };
}

export function viewerBlockingReason(instances: Instance[], complete: boolean, warnings: string[] = []) {
  const { supported, rejected } = partitionSupportedInstances(instances);
  if (rejected.length) {
    const compressed = rejected.filter(({ reason }) => reason === "unsupported-transfer-syntax").length;
    const multiFrame = rejected.filter(({ reason }) => reason === "multi-frame").length;
    const details = [
      compressed ? `${compressed} unsupported or compressed instance${compressed === 1 ? "" : "s"}` : "",
      multiFrame ? `${multiFrame} multi-frame instance${multiFrame === 1 ? "" : "s"}` : "",
    ].filter(Boolean).join(" and ");
    return `Series blocked: ${details}. The controlled pilot does not display a partial diagnostic stack.`;
  }
  if (!complete) return `Series blocked because the source stack is incomplete${warnings.length ? `: ${warnings.join("; ")}` : "."}`;
  if (!supported.length) return "Series blocked because it contains no validated displayable instances.";
  return null;
}

export function buildDicomImageIds(instances: Instance[], dicomUrl: (id: string) => string) {
  return instances.map((instance) => `wadouri:${dicomUrl(instance.id)}`);
}

export function resolveVoiRange(
  presentation: { window_center: number | null; window_width: number | null },
  instance: Pick<Instance, "window_center" | "window_width"> | undefined,
) {
  const center = presentation.window_center ?? instance?.window_center;
  const width = presentation.window_width ?? instance?.window_width;
  if (typeof center !== "number" || !Number.isFinite(center)
      || typeof width !== "number" || !Number.isFinite(width) || width <= 0) return undefined;
  return { lower: center - width / 2, upper: center + width / 2 };
}

export function dicomLoaderHeaders(defaultHeaders: Record<string, string>, authorizationHeaders: Record<string, string>) {
  return { ...defaultHeaders, ...authorizationHeaders };
}

function patientDirectionLabel(vector: number[]) {
  return [
    { magnitude: Math.abs(vector[0]), positive: "L", negative: "R", value: vector[0] },
    { magnitude: Math.abs(vector[1]), positive: "P", negative: "A", value: vector[1] },
    { magnitude: Math.abs(vector[2]), positive: "H", negative: "F", value: vector[2] },
  ].filter((axis) => Number.isFinite(axis.value) && axis.magnitude >= 0.0001)
    .sort((left, right) => right.magnitude - left.magnitude)
    .map((axis) => axis.value >= 0 ? axis.positive : axis.negative).join("");
}

export function orientationLabels(orientation: number[] | null | undefined) {
  if (!orientation || orientation.length !== 6 || orientation.some((value) => !Number.isFinite(value))) return null;
  const row = orientation.slice(0, 3);
  const column = orientation.slice(3, 6);
  const dot = row.reduce((sum, value, index) => sum + value * column[index], 0);
  if (Math.abs(Math.hypot(...row) - 1) > 0.02 || Math.abs(Math.hypot(...column) - 1) > 0.02 || Math.abs(dot) > 0.02) return null;
  return {
    top: patientDirectionLabel(column.map((value) => -value)),
    right: patientDirectionLabel(row),
    bottom: patientDirectionLabel(column),
    left: patientDirectionLabel(row.map((value) => -value)),
  };
}

export function isLengthMeasurementAvailable(hasPixelSpacing: boolean | undefined) {
  return hasPixelSpacing === true;
}

export function viewerErrorMessage(cause: unknown) {
  if (!(cause instanceof Error) || !cause.message.trim()) return "Unable to initialize the DICOM viewer";
  const message = cause.message.trim();
  if (/401|403|unauthori[sz]ed|forbidden/i.test(message)) return "Your imaging session expired or is not authorized. Sign in again before loading this study.";
  if (/worker|webassembly|wasm|codec/i.test(message)) return "The DICOM decoder could not start. Reload the viewer or contact support if the problem continues.";
  return message;
}
