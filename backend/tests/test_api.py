from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

import app as processor_app

client = TestClient(processor_app.app)


def png(width=8, height=6):
    output = BytesIO()
    Image.new("L", (width, height), 127).save(output, "PNG")
    return output.getvalue()


def post_v2(filter_name="box_blur", kernel_size="3", content=None):
    data = {"filter": filter_name}
    if kernel_size is not None:
        data["kernel_size"] = kernel_size
    return client.post("/v2/process", data=data, files={"file": ("input.png", content or png(), "image/png")})


def test_capabilities_describe_backend_and_limits():
    payload = client.get("/v2/capabilities").json()
    assert payload["filters"] == ["box_blur", "sobel"]
    assert payload["limits"]["concurrency"] >= 1


def test_v2_returns_png_and_timing_headers():
    response = post_v2()
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert "process;dur=" in response.headers["server-timing"]
    assert response.headers["x-image-width"] == "8"


def test_v2_validates_inputs_with_stable_errors():
    missing_kernel = post_v2(kernel_size=None)
    assert missing_kernel.status_code == 422
    assert missing_kernel.json()["error"]["code"] == "missing_kernel_size"
    invalid_image = post_v2(content=b"not an image")
    assert invalid_image.status_code == 400
    assert invalid_image.json()["error"]["code"] == "invalid_image"


def test_v2_enforces_upload_and_dimension_limits(monkeypatch):
    monkeypatch.setattr(processor_app, "MAX_UPLOAD_BYTES", 4)
    oversized = post_v2(content=b"12345")
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "upload_too_large"

    monkeypatch.setattr(processor_app, "MAX_UPLOAD_BYTES", 1024 * 1024)
    monkeypatch.setattr(processor_app, "MAX_DIMENSION", 4)
    too_wide = post_v2(content=png(5, 4))
    assert too_wide.status_code == 413
    assert too_wide.json()["error"]["code"] == "image_dimensions_exceeded"


def test_legacy_endpoint_is_compatible_and_deprecated():
    response = client.post("/process", data={"filter_type": "sobel"}, files={"file": ("input.png", png(), "image/png")})
    assert response.status_code == 200
    assert response.headers["deprecation"] == "true"
    assert response.headers["x-processing-metrics"].startswith("{")


def test_bounded_concurrent_requests_complete():
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda _: post_v2("sobel", None), range(4)))
    assert all(response.status_code == 200 for response in responses)
