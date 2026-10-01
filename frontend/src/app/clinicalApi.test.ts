import { afterEach, describe, expect, it, vi } from "vitest";
import { ClinicalApi, isReviewChecklistComplete } from "./clinicalApi";

afterEach(() => vi.unstubAllGlobals());

describe("radiologist review checklist", () => {
  it("blocks review until every safety check is complete", () => {
    expect(isReviewChecklistComplete({
      patient_identity_confirmed: true, laterality_checked: true, priors_checked: true,
      critical_findings_checked: true, warnings_resolved: false,
    })).toBe(false);
  });

  it("allows the reviewed-not-signed transition when all checks are complete", () => {
    expect(isReviewChecklistComplete({
      patient_identity_confirmed: true, laterality_checked: true, priors_checked: true,
      critical_findings_checked: true, warnings_resolved: true,
    })).toBe(true);
  });
});

describe("viewer manifest retrieval", () => {
  it("requests the authenticated, geometry-ordered source manifest", async () => {
    const manifest = { complete: true, warnings: [], series: [{
      id: "series-1", ordering: "patient_geometry", instances: [
        { id: "low", geometry_position: -10 }, { id: "high", geometry_position: 10 },
      ],
    }] };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(manifest), {
      status: 200, headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("window", new EventTarget());
    const api = new ClinicalApi();
    api.token = "test-token";

    await expect(api.viewerManifest("study-1")).resolves.toEqual(manifest);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v3/studies/study-1/viewer-manifest");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("sends the optimistic presentation-state version and reports conflicts", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ version: 4 }), {
        status: 200, headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { message: "Presentation state changed" } }), {
        status: 409, headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);
    const api = new ClinicalApi(); api.token = "test-token";
    const state = {
      version: 3, layout: "1x1" as const, active_series_id: "series-1", active_instance_id: "image-2",
      frame: 0, window_center: 40, window_width: 80, zoom: 1.5, pan_x: 12, pan_y: -4,
      rotation: 0 as const, inverted: true, annotations: [{ metadata: { toolName: "Length" } }],
    };
    await expect(api.savePresentation("study-1", state)).resolves.toEqual({ version: 4 });
    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
    expect(body).toMatchObject({ version: 3, active_instance_id: "image-2", window_center: 40, zoom: 1.5, inverted: true });
    await expect(api.savePresentation("study-1", state)).rejects.toMatchObject({ status: 409 });
  });

  it("clears credentials and announces an expired session", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { message: "Session expired" } }), {
      status: 401, headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("window", new EventTarget());
    const api = new ClinicalApi();
    api.token = "expired-token";
    const listener = vi.fn();
    window.addEventListener("voxura:session-expired", listener);
    await expect(api.studies()).rejects.toThrow("Session expired");
    expect(api.token).toBe("");
    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener("voxura:session-expired", listener);
  });
});
