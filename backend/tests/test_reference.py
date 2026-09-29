import numpy as np

from app import box_blur_reference, sobel_reference


def test_box_blur_uses_replicated_edges_and_rounding():
    image = np.array([[0, 0, 9], [0, 0, 9], [0, 0, 9]], dtype=np.uint8)
    expected = np.array([[0, 3, 6], [0, 3, 6], [0, 3, 6]], dtype=np.uint8)
    np.testing.assert_array_equal(box_blur_reference(image, 3), expected)


def test_sobel_uniform_image_is_zero():
    image = np.full((5, 7), 42, dtype=np.uint8)
    np.testing.assert_array_equal(sobel_reference(image), np.zeros_like(image))


def test_reference_filters_support_tiny_images_and_large_kernels():
    image = np.array([[17]], dtype=np.uint8)
    np.testing.assert_array_equal(box_blur_reference(image, 9), image)
    np.testing.assert_array_equal(sobel_reference(image), np.zeros_like(image))
