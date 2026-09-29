import { describe, expect, it } from "vitest";
import { buildProcessFormData, errorMessage, parseServerTiming } from "./api";

describe("buildProcessFormData", () => {
  it("includes a kernel only for blur", () => {
    const file = new File(["pixels"], "input.png", { type: "image/png" });
    expect(buildProcessFormData(file, "box_blur", 11).get("kernel_size")).toBe("11");
    expect(buildProcessFormData(file, "sobel_edge", 11).has("kernel_size")).toBe(false);
  });
});

describe("parseServerTiming", () => {
  it("extracts named durations", () => {
    expect(parseServerTiming("decode;dur=1.25, process;dur=4.5, total;dur=8")).toEqual({
      decode: 1.25,
      process: 4.5,
      total: 8,
    });
  });

  it("ignores malformed entries", () => {
    expect(parseServerTiming("process;desc=work, total;dur=nope")).toEqual({});
  });
});

describe("errorMessage", () => {
  it("uses structured API errors", async () => {
    const response = new Response(JSON.stringify({ error: { code: "bad", message: "Try another image" } }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
    await expect(errorMessage(response)).resolves.toBe("Try another image");
  });

  it("falls back to the status", async () => {
    await expect(errorMessage(new Response("oops", { status: 500 }))).resolves.toBe("Processing failed (500)");
  });
});
