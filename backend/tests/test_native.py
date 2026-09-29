import numpy as np
import pytest

from app import box_blur_reference, sobel_reference

native = pytest.importorskip("image_processor")


@pytest.mark.parametrize("shape", [(1, 1), (2, 3), (17, 19)])
@pytest.mark.parametrize("kernel", [3, 5, 11])
def test_native_blur_matches_reference(shape, kernel):
    source = np.arange(np.prod(shape), dtype=np.uint8).reshape(shape)
    actual = source.copy()
    native.box_blur(actual, kernel)
    np.testing.assert_array_equal(actual, box_blur_reference(source, kernel))


@pytest.mark.parametrize("shape", [(1, 1), (2, 3), (17, 19)])
def test_native_sobel_matches_reference(shape):
    source = np.arange(np.prod(shape), dtype=np.uint8).reshape(shape)
    actual = source.copy()
    native.sobel_edge(actual)
    np.testing.assert_allclose(actual, sobel_reference(source), atol=1)


@pytest.mark.parametrize("image", [
    np.zeros((4, 4), dtype=np.float32),
    np.zeros((4, 8), dtype=np.uint8)[:, ::2],
    np.zeros((2, 2, 3), dtype=np.uint8),
])
def test_native_rejects_incompatible_arrays(image):
    with pytest.raises((TypeError, ValueError)):
        native.sobel_edge(image)


def test_native_rejects_read_only_array():
    image = np.zeros((4, 4), dtype=np.uint8)
    image.flags.writeable = False
    with pytest.raises(ValueError):
        native.box_blur(image, 3)


@pytest.mark.parametrize("kernel", [1, 4])
def test_native_rejects_invalid_kernel(kernel):
    with pytest.raises(ValueError):
        native.box_blur(np.zeros((4, 4), dtype=np.uint8), kernel)
