import { useEffect, useState } from "react";
import { clinicalApi, type Reviewer, type ReviewerInput } from "./clinicalApi";

const empty: ReviewerInput = { name: "", affiliation: "", expertise: "", source_url: "" };
const nominees: ReviewerInput[] = [
  { name: "Hugo Aerts", affiliation: "TCIA NSCLC-Radiomics contributor", expertise: "CT radiomics", source_url: "https://www.cancerimagingarchive.net/collection/nsclc-radiomics/" },
  { name: "Philippe Lambin", affiliation: "TCIA NSCLC-Radiomics contributor", expertise: "CT radiomics", source_url: "https://www.cancerimagingarchive.net/collection/nsclc-radiomics/" },
  { name: "Justin Kirby", affiliation: "TCIA contact nominated by project owner", expertise: "Data governance", source_url: "https://www.cancerimagingarchive.net/" },
  { name: "Fred Prior", affiliation: "TCIA contact nominated by project owner", expertise: "Data governance", source_url: "https://www.cancerimagingarchive.net/" },
  { name: "Kenneth Aldape", affiliation: "TCGA brain collection contact nominated by project owner", expertise: "Brain tumor pathology", source_url: "https://www.cancerimagingarchive.net/collection/tcga-gbm/" },
  { name: "Michael P. Recht", affiliation: "NYU fastMRI investigator", expertise: "MR image quality", source_url: "https://fastmri.med.nyu.edu/" },
  { name: "Yvonne W. Lui", affiliation: "NYU fastMRI investigator", expertise: "Brain MR", source_url: "https://fastmri.med.nyu.edu/" },
  { name: "Matteo Maspero", affiliation: "SynthRAD2023 contributor", expertise: "MR/CT radiotherapy imaging", source_url: "https://zenodo.org/records/7260705" },
  { name: "Cornelis A. T. van den Berg", affiliation: "SynthRAD2023 contributor", expertise: "MR/CT radiotherapy imaging", source_url: "https://zenodo.org/records/7260705" },
  { name: "Stephen Smith", affiliation: "UK Biobank contact nominated by project owner", expertise: "Brain MR methods", source_url: "https://www.ukbiobank.ac.uk/use-our-data/" },
  { name: "Stefan Neubauer", affiliation: "UK Biobank contact nominated by project owner", expertise: "Cardiac MR", source_url: "https://www.ukbiobank.ac.uk/use-our-data/" },
];

export function ReviewerDirectory({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<Reviewer[]>([]);
  const [form, setForm] = useState<ReviewerInput>(empty);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void clinicalApi.reviewers().then((response) => setItems(response.items)).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "Reviewer list unavailable"));
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true); setError("");
    try {
      const added = await clinicalApi.addReviewer(form);
      setItems((previous) => [added, ...previous]);
      setForm(empty);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add reviewer");
    } finally { setSaving(false); }
  }

  return <section className="h-full overflow-auto bg-slate-100 p-6 text-slate-950" aria-label="Reviewer directory">
    <div className="mx-auto max-w-4xl">
      <button onClick={onClose} className="mb-4 text-sm font-semibold text-cyan-800 underline">Back to worklist</button>
      <h2 className="text-2xl font-semibold">Reviewer directory</h2>
      <p className="mt-2 text-sm text-slate-700">Add proposed reviewers for your institution. Listing a person does not grant access, appoint them, or record approval of a clinical release gate.</p>
      <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-4"><h3 className="font-semibold">Project owner nominations</h3><p className="mt-1 text-xs text-amber-900">These contacts have not confirmed a Voxura role. Select one to fill the form, then verify the details before adding.</p><div className="mt-3 flex flex-wrap gap-2">{nominees.map((nominee) => <button key={nominee.name} type="button" onClick={() => setForm(nominee)} className="rounded border border-amber-400 bg-white px-2 py-1 text-xs hover:bg-amber-100">{nominee.name}</button>)}</div></div>
      {error && <p role="alert" className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      <form onSubmit={(event) => void submit(event)} className="mt-6 grid gap-3 rounded-lg border bg-white p-4 sm:grid-cols-2">
        {(["name", "affiliation", "expertise", "source_url"] as const).map((field) => <label key={field} className="text-sm font-medium capitalize">{field.replace("_", " ")}
          <input required={field !== "source_url"} maxLength={field === "source_url" ? 500 : 200} value={form[field]} onChange={(event) => setForm({ ...form, [field]: event.target.value })} className="mt-1 w-full rounded border border-slate-300 p-2 font-normal" />
        </label>)}
        <button disabled={saving} className="rounded bg-cyan-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 sm:col-span-2">{saving ? "Adding…" : "Add proposed reviewer"}</button>
      </form>
      <ul className="mt-6 space-y-3">{items.map((item) => <li key={item.id} className="rounded-lg border bg-white p-4"><strong>{item.name}</strong><span className="ml-2 rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">Proposed</span><p className="text-sm text-slate-700">{item.affiliation} · {item.expertise}</p>{item.source_url && <p className="mt-1 break-all text-xs text-slate-500">{item.source_url}</p>}</li>)}</ul>
    </div>
  </section>;
}
