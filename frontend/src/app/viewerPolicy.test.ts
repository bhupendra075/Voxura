import { describe, expect, it } from "vitest";
import type { Instance } from "./clinicalApi";
import { buildDicomImageIds, dicomLoaderHeaders, isLengthMeasurementAvailable, orientationLabels, partitionSupportedInstances, viewerBlockingReason, viewerErrorMessage } from "./viewerPolicy";

const instance = (id: string, transfer_syntax = "1.2.840.10008.1.2.1", frame_count = 1): Instance => ({
  id, transfer_syntax, frame_count, instance_number: 1,
});

describe("controlled-pilot viewer policy", () => {
  it("builds wadouri image IDs without changing manifest order", () => {
    expect(buildDicomImageIds([instance("one"), instance("id/with spaces")], (id) => `/v3/instances/${encodeURIComponent(id)}/dicom`)).toEqual([
      "wadouri:/v3/instances/one/dicom",
      "wadouri:/v3/instances/id%2Fwith%20spaces/dicom",
    ]);
  });

  it("accepts only validated uncompressed, single-frame instances", () => {
    const result = partitionSupportedInstances([
      instance("implicit", "1.2.840.10008.1.2"), instance("explicit-le"),
      instance("explicit-be", "1.2.840.10008.1.2.2"),
      instance("jpeg", "1.2.840.10008.1.2.4.50"), instance("enhanced", "1.2.840.10008.1.2.1", 12),
    ]);
    expect(result.supported.map(({ id }) => id)).toEqual(["implicit", "explicit-le", "explicit-be"]);
    expect(result.rejected.map(({ instance: item, reason }) => [item.id, reason])).toEqual([
      ["jpeg", "unsupported-transfer-syntax"], ["enhanced", "multi-frame"],
    ]);
  });

  it("gates calibrated length on an explicit pixel-spacing signal", () => {
    expect(isLengthMeasurementAvailable(true)).toBe(true);
    expect(isLengthMeasurementAvailable(false)).toBe(false);
    expect(isLengthMeasurementAvailable(undefined)).toBe(false);
  });

  it("produces no image IDs when a study switch clears the stack", () => {
    expect(partitionSupportedInstances([])).toEqual({ supported: [], rejected: [] });
    expect(buildDicomImageIds([], () => "/unused")).toEqual([]);
  });

  it("blocks partial display when any compressed, multi-frame, or incomplete source is present", () => {
    expect(viewerBlockingReason([instance("ok"), instance("jpeg", "1.2.840.10008.1.2.4.50")], true)).toContain("partial diagnostic stack");
    expect(viewerBlockingReason([instance("enhanced", "1.2.840.10008.1.2.1", 2)], true)).toContain("multi-frame");
    expect(viewerBlockingReason([instance("ok")], false, ["missing geometry"])).toContain("missing geometry");
    expect(viewerBlockingReason([instance("ok")], true)).toBeNull();
  });

  it("preserves actionable viewer errors and safely labels unknown failures", () => {
    expect(viewerErrorMessage(new Error("DICOM transfer syntax is unsupported"))).toBe("DICOM transfer syntax is unsupported");
    expect(viewerErrorMessage({ reason: "worker failed" })).toBe("Unable to initialize the DICOM viewer");
    expect(viewerErrorMessage(new Error(""))).toBe("Unable to initialize the DICOM viewer");
    expect(viewerErrorMessage(new Error("Request failed with status 401"))).toContain("session expired");
    expect(viewerErrorMessage(new Error("WebAssembly codec worker failed"))).toContain("decoder could not start");
  });

  it("preserves loader defaults while adding current authorization", () => {
    expect(dicomLoaderHeaders({ Accept: "application/dicom", "X-Loader": "required" }, { Authorization: "Bearer current" })).toEqual({
      Accept: "application/dicom", "X-Loader": "required", Authorization: "Bearer current",
    });
  });

  it("shows orientation only for valid orthonormal patient geometry", () => {
    expect(orientationLabels([1, 0, 0, 0, 1, 0])).toEqual({ top: "A", right: "L", bottom: "P", left: "R" });
    expect(orientationLabels([0, -1, 0, 1, 0, 0])).toEqual({ top: "R", right: "A", bottom: "L", left: "P" });
    expect(orientationLabels([1, 0, 0, 0, 0, -1])).toEqual({ top: "H", right: "L", bottom: "F", left: "R" });
    expect(orientationLabels([0, 1, 0, 0, 0, -1])).toEqual({ top: "H", right: "P", bottom: "F", left: "A" });
    expect(orientationLabels([Math.SQRT1_2, Math.SQRT1_2, 0, 0, 0, 1])).toEqual({ top: "F", right: "LP", bottom: "H", left: "RA" });
    expect(orientationLabels([1, 0, 0, 1, 0, 0])).toBeNull();
    expect(orientationLabels([2, 0, 0, 0, 1, 0])).toBeNull();
    expect(orientationLabels([1, 0, 0, 0.1, 0.995, 0])).toBeNull();
    expect(orientationLabels([1, 0, 0])).toBeNull();
  });
});
