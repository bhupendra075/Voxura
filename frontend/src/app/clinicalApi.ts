import { API_BASE_URL } from "./api";

export interface SessionUser { id: string; display_name: string; role: string }
export interface Reviewer { id: string; name: string; affiliation: string; expertise: string; source_url: string; status: "proposed"; created_at: number }
export type ReviewerInput = Pick<Reviewer, "name" | "affiliation" | "expertise" | "source_url">;
export interface Study {
  id: string; patient_name: string; patient_id: string; birth_date: string; sex: string;
  accession: string; study_date: string; description: string; modalities: string; status: string;
}
export interface Series {
  id: string; modality: string; series_number: number | null; description: string; laterality: string;
  rows: number | null; columns: number | null; instance_count: number; frame_count: number;
  has_geometry?: boolean; has_pixel_spacing?: boolean; warnings?: string[];
}
export interface Instance {
  id: string; instance_number: number | null; frame_count: number; transfer_syntax: string;
  orientation?: number[] | null; window_center?: number | null; window_width?: number | null;
}
export interface ViewerManifestSeries extends Series {
  ordering: "patient_geometry" | "instance_number_fallback";
  complete: boolean;
  measurement_calibrated: boolean;
  instances: Array<Instance & {
    sha256: string; geometry_position: number | null; orientation: number[] | null;
    position: number[] | null; pixel_spacing: number[] | null;
  }>;
}
export interface ViewerManifest {
  study: Study; evaluation_only: boolean; source_pixels_immutable: boolean;
  complete: boolean; warnings: string[]; series: ViewerManifestSeries[];
}
export interface SeriesMetadata { study: Study; series: Series; instances: Instance[] }
export interface PresentationState {
  version: number;
  layout: "1x1" | "1x2" | "2x2"; active_series_id: string | null; active_instance_id: string | null;
  frame: number; window_center: number | null; window_width: number | null; zoom: number;
  pan_x: number; pan_y: number; rotation: 0 | 90 | 180 | 270; inverted: boolean;
  annotations: Array<Record<string, unknown>>;
}

export class ClinicalApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); this.name = "ClinicalApiError"; }
}
export interface ModelCapability {
  id: string; display_name: string; version: string; status: string; intended_use: string;
  required_sequences: string[]; jurisdictions: string[]; license: string; checksum: string | null; enabled: boolean;
}
export interface AiCapabilities {
  intended_use: string; worker: { configured: boolean; backend: string }; profiles: string[];
  models: ModelCapability[]; safety: { automatic_signing: boolean; generic_diagnosis_endpoint: boolean; abstention_required: boolean };
}
export interface AnalysisJob {
  id: string; study_id: string; profile: string; prior_study_id: string | null;
  state: "queued" | "qualifying" | "running" | "completed" | "partial" | "abstained" | "cancelled" | "failed";
  message: string; manifest: { series_count: number; sequences: string[]; warnings: string[] };
  modules: Array<{ model_id: string; display_name: string; state: string; missing_sequences: string[] }>;
  created_at: number; updated_at: number;
}
export interface AnalysisResults { items: Array<Record<string, unknown>>; latest_job: AnalysisJob | null }
export interface ReportDraft {
  version: number; status: "empty" | "draft" | "reviewed"; findings_text: string; impression_text: string;
  updated_by: string | null; updated_at: number | null;
}
export interface ReviewChecklist {
  patient_identity_confirmed: boolean; laterality_checked: boolean; priors_checked: boolean;
  critical_findings_checked: boolean; warnings_resolved: boolean;
}

export function isReviewChecklistComplete(checklist: ReviewChecklist): boolean {
  return Object.values(checklist).every(Boolean);
}

const TOKEN_KEY = "clinical-viewer-token";
const DEVELOPMENT_SESSION_ENABLED = import.meta.env.VITE_CLINICAL_DEV_SESSION === "true";

export class ClinicalApi {
  token = typeof sessionStorage === "undefined" ? "" : sessionStorage.getItem(TOKEN_KEY) ?? "";

  authorizationHeaders(): Record<string, string> {
    return this.token ? { Authorization: `Bearer ${this.token}` } : {};
  }

  dicomUrl(instanceId: string): string {
    return `${API_BASE_URL}/v3/instances/${encodeURIComponent(instanceId)}/dicom`;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try {
        const payload = await response.json() as { detail?: string | { message?: string }; error?: { message?: string } };
        message = typeof payload.detail === "string" ? payload.detail : payload.detail?.message ?? payload.error?.message ?? message;
      } catch { /* keep status message */ }
      if (response.status === 401 || response.status === 403) {
        this.token = "";
        if (typeof sessionStorage !== "undefined") sessionStorage.removeItem(TOKEN_KEY);
        if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("voxura:session-expired", { detail: { message } }));
      }
      throw new ClinicalApiError(message, response.status);
    }
    const contentType = response.headers.get("content-type") ?? "";
    return (contentType.includes("application/json") ? response.json() : response.blob()) as Promise<T>;
  }

  async ensureDevelopmentSession(): Promise<SessionUser> {
    if (!this.token) {
      if (!DEVELOPMENT_SESSION_ENABLED) {
        throw new Error("Sign in through the institution identity provider to access clinical studies");
      }
      const session = await this.request<{ access_token: string; user: SessionUser }>("/v3/session/dev", { method: "POST" });
      this.token = session.access_token;
      if (typeof sessionStorage !== "undefined") sessionStorage.setItem(TOKEN_KEY, this.token);
      return session.user;
    }
    const session = await this.request<{ user?: Partial<SessionUser>; id?: string; display_name?: string; role?: string }>("/v3/session");
    const user = session.user ?? session;
    if (!user.id || !user.role) throw new Error("The authenticated session is missing required user identity fields");
    return { id: user.id, role: user.role, display_name: user.display_name || user.id };
  }

  studies(query = "") { return this.request<{ items: Study[]; total: number }>(`/v3/studies${query ? `?patient=${encodeURIComponent(query)}` : ""}`); }
  reviewers() { return this.request<{ items: Reviewer[] }>("/v3/reviewers"); }
  addReviewer(input: ReviewerInput) { return this.request<Reviewer>("/v3/reviewers", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) }); }
  series(studyId: string) { return this.request<{ items: Series[] }>(`/v3/studies/${studyId}/series`); }
  viewerManifest(studyId: string) { return this.request<ViewerManifest>(`/v3/studies/${studyId}/viewer-manifest`); }
  metadata(studyId: string, seriesId: string) { return this.request<SeriesMetadata>(`/v3/studies/${studyId}/series/${seriesId}/metadata`); }
  report(studyId: string) { return this.request<{ status: string; text: string; updated_at: number | null }>(`/v3/studies/${studyId}/report`); }
  aiCapabilities() { return this.request<AiCapabilities>("/v3/ai/capabilities"); }
  analysisResults(studyId: string) { return this.request<AnalysisResults>(`/v3/studies/${studyId}/analysis-results`); }
  createAnalysis(studyId: string) {
    return this.request<AnalysisJob>(`/v3/studies/${studyId}/analysis-jobs`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile: "brain_mri_assist_v1" }),
    });
  }
  reportDraft(studyId: string) { return this.request<ReportDraft>(`/v3/studies/${studyId}/report-draft`); }
  saveReportDraft(studyId: string, draft: Pick<ReportDraft, "version" | "findings_text" | "impression_text">) {
    return this.request<ReportDraft>(`/v3/studies/${studyId}/report-draft`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft),
    });
  }
  reviewReportDraft(studyId: string, version: number, checklist: ReviewChecklist) {
    return this.request<ReportDraft>(`/v3/studies/${studyId}/report-draft/review`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        version, ...checklist,
      }),
    });
  }
  pacsHealth() { return this.request<{ configured: boolean; reachable: boolean; message: string }>("/v3/pacs/health"); }
  presentation(studyId: string) { return this.request<PresentationState>(`/v3/studies/${studyId}/presentation-state`); }
  savePresentation(studyId: string, state: PresentationState) {
    return this.request<PresentationState>(`/v3/studies/${studyId}/presentation-state`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state),
    });
  }
  async import(files: File[]) {
    const form = new FormData(); files.forEach((file) => form.append("files", file));
    return this.request<{ accepted: Array<{ study_id: string }>; rejected: Array<{ filename: string; reason: string }> }>("/v3/import", { method: "POST", body: form });
  }
  async frame(instanceId: string, frame: number, center: number | null, width: number | null, invert: boolean) {
    const params = new URLSearchParams({ invert: String(invert) });
    if (center !== null && width !== null) { params.set("window_center", String(center)); params.set("window_width", String(width)); }
    return this.request<Blob>(`/v3/instances/${instanceId}/frames/${frame}/rendered?${params}`);
  }
}

export const clinicalApi = new ClinicalApi();
