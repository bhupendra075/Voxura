#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <cstdint>

namespace image_processor {

// Apply Box Blur filter using separable 2D convolution.
// Uses OpenMP for multi-threaded pixel processing.
// Zero-copy: modifies the input array in-place via pybind11 buffer protocol.
// @param image 2D uint8_t NumPy array (height x width), modified in-place
// @param kernel_size Size of the blur kernel (must be odd, >= 3)
void box_blur(pybind11::array_t<uint8_t>& image, int kernel_size);

// Apply Sobel Edge Detection filter.
// Computes gradient magnitude using 3x3 Sobel kernels (Gx, Gy).
// Uses OpenMP for multi-threaded pixel processing.
// Zero-copy: modifies the input array in-place via pybind11 buffer protocol.
// @param image 2D uint8_t NumPy array (height x width), modified in-place
void sobel_edge(pybind11::array_t<uint8_t>& image);

bool openmp_enabled();
int openmp_max_threads();

} // namespace image_processor
