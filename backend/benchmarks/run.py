"""Reproducible, non-destructive native/OpenCV benchmark.

Prints JSON to stdout. Use --output only when a report file is explicitly wanted.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import app


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * quantile))]


def invoke(source: np.ndarray, filter_name: str, kernel: int, backend: str) -> float:
    image = source.copy()
    started = time.perf_counter()
    if backend == "native":
        if filter_name == "box_blur":
            app.native_processor.box_blur(image, kernel)
        else:
            app.native_processor.sobel_edge(image)
    elif filter_name == "box_blur":
        image[:] = app.cv2.blur(image, (kernel, kernel), borderType=app.cv2.BORDER_REPLICATE)
    else:
        image[:] = app.sobel_reference(image)
    return (time.perf_counter() - started) * 1000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--allow-fallback", action="store_true")
    parser.add_argument("--baseline", type=Path, help="Fail if a matching median regresses by more than --max-regression")
    parser.add_argument("--max-regression", type=float, default=0.10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if app.native_processor is None and not args.allow_fallback:
        raise SystemExit("Native module unavailable; build/install the backend or pass --allow-fallback")

    rng = np.random.default_rng(20260929)
    backends = [name for name, available in (("native", app.native_processor is not None), ("opencv", app.cv2 is not None)) if available]
    if app.native_processor is not None:
        probe = rng.integers(0, 256, (97, 89), dtype=np.uint8)
        for filter_name, kernel in (("box_blur", 11), ("sobel", 3)):
            actual = probe.copy()
            if filter_name == "box_blur":
                app.native_processor.box_blur(actual, kernel)
                expected = app.box_blur_reference(probe, kernel)
            else:
                app.native_processor.sobel_edge(actual)
                expected = app.sobel_reference(probe)
            if not np.allclose(actual, expected, atol=1):
                raise SystemExit(f"Correctness check failed for native {filter_name}")
    rows = []
    for size in (512, 1024, 2048, 4096):
        source = rng.integers(0, 256, (size, size), dtype=np.uint8)
        for filter_name, kernels in (("box_blur", (3, 11, 51)), ("sobel", (3,))):
            for kernel in kernels:
                for backend in backends:
                    for _ in range(args.warmups):
                        invoke(source, filter_name, kernel, backend)
                    samples = [invoke(source, filter_name, kernel, backend) for _ in range(args.repetitions)]
                    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                        started = time.perf_counter()
                        list(pool.map(lambda _: invoke(source, filter_name, kernel, backend), range(args.concurrency)))
                        concurrent_ms = (time.perf_counter() - started) * 1000
                    rows.append({
                        "backend": backend, "filter": filter_name, "size": size, "kernel": kernel,
                        "median_ms": statistics.median(samples), "p95_ms": percentile(samples, 0.95),
                        "concurrent_requests": args.concurrency, "concurrent_total_ms": concurrent_ms,
                    })

    report = {"schema_version": 1, "warmups": args.warmups, "repetitions": args.repetitions, "results": rows}
    if args.baseline:
        previous = json.loads(args.baseline.read_text(encoding="utf-8"))
        keys = ("backend", "filter", "size", "kernel")
        indexed = {tuple(row[key] for key in keys): row for row in previous["results"]}
        regressions = []
        for row in rows:
            baseline = indexed.get(tuple(row[key] for key in keys))
            if baseline and row["median_ms"] > baseline["median_ms"] * (1 + args.max_regression):
                regressions.append({"case": {key: row[key] for key in keys}, "baseline_ms": baseline["median_ms"], "current_ms": row["median_ms"]})
        report["regressions"] = regressions
        if regressions:
            print(json.dumps(report, indent=2))
            raise SystemExit(f"{len(regressions)} benchmark regression(s) exceeded the threshold")
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
