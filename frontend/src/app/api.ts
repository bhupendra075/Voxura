export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export function buildProcessFormData(file: File, filter: "box_blur" | "sobel_edge", kernelSize: number): FormData {
  const form = new FormData();
  form.append("file", file);
  form.append("filter", filter === "box_blur" ? "box_blur" : "sobel");
  if (filter === "box_blur") form.append("kernel_size", kernelSize.toString());
  return form;
}

export function parseServerTiming(header: string | null): Record<string, number> {
  if (!header) return {};
  return Object.fromEntries(
    header.split(",").flatMap((entry) => {
      const [name, ...parameters] = entry.trim().split(";");
      const duration = parameters.find((value) => value.trim().startsWith("dur="));
      const parsed = duration ? Number.parseFloat(duration.trim().slice(4)) : Number.NaN;
      return name && Number.isFinite(parsed) ? [[name, parsed]] : [];
    }),
  );
}

export async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = await response.json() as { error?: { message?: string } };
    if (payload.error?.message) return payload.error.message;
  } catch {
    // Fall back to the status below when the response is not JSON.
  }
  return `Processing failed (${response.status})`;
}
