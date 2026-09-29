from __future__ import annotations

import asyncio
import io
import json
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import image_processor as native_processor
except ImportError:
    native_processor = None

try:
    import cv2
except ImportError:
    cv2 = None


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}")
    return value


MAX_UPLOAD_BYTES = _env_int("PROCESSOR_MAX_UPLOAD_BYTES", 20 * 1024 * 1024)
MAX_DIMENSION = _env_int("PROCESSOR_MAX_DIMENSION", 8192)
MAX_MEGAPIXELS = _env_int("PROCESSOR_MAX_MEGAPIXELS", 40)
MAX_KERNEL_SIZE = _env_int("PROCESSOR_MAX_KERNEL_SIZE", 101, 3)
MAX_CONCURRENCY = _env_int("PROCESSOR_MAX_CONCURRENCY", 2)
REQUIRE_NATIVE = os.getenv("PROCESSOR_REQUIRE_NATIVE", "0").lower() in {"1", "true", "yes"}
ALLOWED_ORIGINS = [value.strip() for value in os.getenv(
    "PROCESSOR_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if value.strip()]

if REQUIRE_NATIVE and native_processor is None:
    raise RuntimeError("PROCESSOR_REQUIRE_NATIVE is enabled, but image_processor could not be imported")

# Explicit dimension and pixel checks below provide deterministic API errors.
Image.MAX_IMAGE_PIXELS = None
_processing_slots = threading.BoundedSemaphore(MAX_CONCURRENCY)


class FilterName(str, Enum):
    box_blur = "box_blur"
    sobel = "sobel"


class ProcessorError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProcessedImage:
    png: bytes
    width: int
    height: int
    backend: str
    timings_ms: dict[str, float]


def box_blur_reference(arr: np.ndarray, kernel_size: int) -> np.ndarray:
    radius = kernel_size // 2
    padded = np.pad(arr, ((radius, radius), (radius, radius)), mode="edge").astype(np.uint64)
    integral = np.pad(padded, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    sums = (
        integral[kernel_size:, kernel_size:]
        - integral[:-kernel_size, kernel_size:]
        - integral[kernel_size:, :-kernel_size]
        + integral[:-kernel_size, :-kernel_size]
    )
    return ((sums + (kernel_size * kernel_size) // 2) // (kernel_size * kernel_size)).astype(np.uint8)


def sobel_reference(arr: np.ndarray) -> np.ndarray:
    padded = np.pad(arr.astype(np.int32), 1, mode="edge")
    p00, p01, p02 = padded[:-2, :-2], padded[:-2, 1:-1], padded[:-2, 2:]
    p10, p12 = padded[1:-1, :-2], padded[1:-1, 2:]
    p20, p21, p22 = padded[2:, :-2], padded[2:, 1:-1], padded[2:, 2:]
    gx = -p00 + p02 - 2 * p10 + 2 * p12 - p20 + p22
    gy = -p00 - 2 * p01 - p02 + p20 + 2 * p21 + p22
    squared = gx.astype(np.int64) ** 2 + gy.astype(np.int64) ** 2
    maximum = int(squared.max(initial=0))
    if maximum == 0:
        return np.zeros_like(arr)
    scale = 255.0 / np.sqrt(maximum)
    return np.clip(np.sqrt(squared) * scale + 0.5, 0, 255).astype(np.uint8)


# Backward-compatible names used by older scripts.
box_blur_py = box_blur_reference
sobel_edge_py = sobel_reference


def _validate_kernel(filter_name: FilterName, kernel_size: int | None) -> int:
    if filter_name is FilterName.sobel:
        return 3
    if kernel_size is None:
        raise ProcessorError(422, "missing_kernel_size", "kernel_size is required for box_blur")
    if kernel_size < 3 or kernel_size > MAX_KERNEL_SIZE or kernel_size % 2 == 0:
        raise ProcessorError(422, "invalid_kernel_size", f"kernel_size must be odd and between 3 and {MAX_KERNEL_SIZE}")
    return kernel_size


def _decode(contents: bytes) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(contents)) as source:
            width, height = source.size
            if width <= 0 or height <= 0 or width > MAX_DIMENSION or height > MAX_DIMENSION:
                raise ProcessorError(413, "image_dimensions_exceeded", f"image dimensions must not exceed {MAX_DIMENSION}x{MAX_DIMENSION}")
            if width * height > MAX_MEGAPIXELS * 1_000_000:
                raise ProcessorError(413, "image_pixels_exceeded", f"image must not exceed {MAX_MEGAPIXELS} megapixels")
            image = ImageOps.exif_transpose(source).convert("L")
            return np.array(image, dtype=np.uint8, copy=True, order="C")
    except ProcessorError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProcessorError(400, "invalid_image", "The uploaded file is not a supported image") from exc


def _apply_filter(arr: np.ndarray, filter_name: FilterName, kernel_size: int) -> str:
    if native_processor is not None:
        if filter_name is FilterName.box_blur:
            native_processor.box_blur(arr, kernel_size)
        else:
            native_processor.sobel_edge(arr)
        return "native-openmp" if native_processor.openmp_enabled() else "native"
    if cv2 is not None:
        if filter_name is FilterName.box_blur:
            arr[:] = cv2.blur(arr, (kernel_size, kernel_size), borderType=cv2.BORDER_REPLICATE)
        else:
            # The reference implementation defines exact normalization and border behavior.
            arr[:] = sobel_reference(arr)
        return "opencv"
    if filter_name is FilterName.box_blur:
        arr[:] = box_blur_reference(arr, kernel_size)
    else:
        arr[:] = sobel_reference(arr)
    return "numpy"


def _process_sync(contents: bytes, filter_name: FilterName, kernel_size: int) -> ProcessedImage:
    total_start = time.perf_counter()
    start = time.perf_counter()
    arr = _decode(contents)
    decode_ms = (time.perf_counter() - start) * 1000
    height, width = arr.shape

    start = time.perf_counter()
    backend = _apply_filter(arr, filter_name, kernel_size)
    process_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    output = io.BytesIO()
    Image.fromarray(arr).save(output, format="PNG", optimize=False)
    encode_ms = (time.perf_counter() - start) * 1000
    total_ms = (time.perf_counter() - total_start) * 1000
    return ProcessedImage(output.getvalue(), width, height, backend, {
        "decode": decode_ms, "process": process_ms, "encode": encode_ms, "total": total_ms,
    })


def _process_sync_limited(contents: bytes, filter_name: FilterName, kernel_size: int) -> ProcessedImage:
    with _processing_slots:
        return _process_sync(contents, filter_name, kernel_size)


def _headers(result: ProcessedImage, filter_name: FilterName, kernel_size: int) -> dict[str, str]:
    timing = result.timings_ms
    return {
        "Server-Timing": ", ".join(f"{name};dur={duration:.3f}" for name, duration in timing.items()),
        "X-Processor-Backend": result.backend,
        "X-Image-Width": str(result.width),
        "X-Image-Height": str(result.height),
        "X-Processing-Mode": filter_name.value,
        "X-Kernel-Size": str(kernel_size),
    }


async def _read_upload(file: UploadFile) -> bytes:
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if not contents:
        raise ProcessorError(400, "empty_upload", "The uploaded file is empty")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise ProcessorError(413, "upload_too_large", f"Upload must not exceed {MAX_UPLOAD_BYTES} bytes")
    return contents


async def _run(file: UploadFile, filter_name: FilterName, kernel_size: int | None) -> tuple[ProcessedImage, int]:
    kernel = _validate_kernel(filter_name, kernel_size)
    contents = await _read_upload(file)
    result = await asyncio.to_thread(_process_sync_limited, contents, filter_name, kernel)
    return result, kernel


app = FastAPI(title="High-Performance Image Processor", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Server-Timing", "X-Processor-Backend", "X-Image-Width", "X-Image-Height", "X-Processing-Mode", "X-Kernel-Size", "Deprecation", "Sunset"],
)

# The clinical v3 surface is isolated from the legacy image-filter API so the
# source DICOM path never mutates or reuses processed demo pixels.
from clinical import initialize_clinical_store, router as clinical_router

initialize_clinical_store()
app.include_router(clinical_router)


@app.exception_handler(ProcessorError)
async def processor_error_handler(_: Request, exc: ProcessorError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [".".join(str(part) for part in error["loc"] if part != "body") for error in exc.errors()]
    return JSONResponse(status_code=422, content={"error": {
        "code": "validation_error",
        "message": "Invalid request fields",
        "fields": fields,
    }})


@app.get("/v2/capabilities")
def capabilities() -> dict[str, Any]:
    native = native_processor is not None
    return {
        "api_version": "v2",
        "filters": [item.value for item in FilterName],
        "backend": "native-openmp" if native and native_processor.openmp_enabled() else ("native" if native else ("opencv" if cv2 is not None else "numpy")),
        "native_available": native,
        "openmp_available": bool(native and native_processor.openmp_enabled()),
        "openmp_max_threads": native_processor.openmp_max_threads() if native else 0,
        "limits": {"upload_bytes": MAX_UPLOAD_BYTES, "dimension": MAX_DIMENSION, "megapixels": MAX_MEGAPIXELS, "kernel_size": MAX_KERNEL_SIZE, "concurrency": MAX_CONCURRENCY},
    }


@app.post("/v2/process")
async def process_v2(
    file: UploadFile = File(...),
    filter: FilterName = Form(...),
    kernel_size: int | None = Form(None),
) -> Response:
    result, kernel = await _run(file, filter, kernel_size)
    return Response(result.png, media_type="image/png", headers=_headers(result, filter, kernel))


@app.post("/process", deprecated=True)
async def process_legacy(
    file: UploadFile = File(...),
    filter_type: str = Form("blur"),
    kernel_size: int = Form(3),
) -> Response:
    mapping = {"blur": FilterName.box_blur, "box_blur": FilterName.box_blur, "sobel": FilterName.sobel, "sobel_edge": FilterName.sobel}
    filter_name = mapping.get(filter_type.lower())
    if filter_name is None:
        raise ProcessorError(422, "invalid_filter", "filter_type must be blur or sobel")
    result, kernel = await _run(file, filter_name, kernel_size)
    headers = _headers(result, filter_name, kernel)
    headers.update({
        "Deprecation": "true",
        "Sunset": "Wed, 31 Dec 2026 23:59:59 GMT",
        "Link": '</v2/process>; rel="successor-version"',
        "X-Processing-Metrics": json.dumps({"c_function_seconds": result.timings_ms["process"] / 1000, "filter": filter_type, "kernel_size": kernel}),
    })
    return Response(result.png, media_type="image/png", headers=headers)
