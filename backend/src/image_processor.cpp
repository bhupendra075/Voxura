#include "image_processor.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <vector>

#ifdef _OPENMP
#include <omp.h>
#endif

namespace image_processor {
namespace {
inline int clamp_index(int value, int upper) { return std::max(0, std::min(upper - 1, value)); }
inline uint8_t rounded_average(uint64_t sum, uint64_t count) {
    return static_cast<uint8_t>((sum + count / 2) / count);
}
}  // namespace

void box_blur(pybind11::array_t<uint8_t>& image, int kernel_size) {
    if (kernel_size < 3 || kernel_size % 2 == 0) {
        throw std::invalid_argument("kernel_size must be odd and >= 3");
    }
    const pybind11::buffer_info buf = image.request();
    if (buf.ndim != 2) throw std::invalid_argument("expected a 2D grayscale image");
    const int height = static_cast<int>(buf.shape[0]);
    const int width = static_cast<int>(buf.shape[1]);
    if (height == 0 || width == 0) return;

    auto* data = static_cast<uint8_t*>(buf.ptr);
    const int stride = static_cast<int>(buf.strides[0]);
    const int radius = kernel_size / 2;
    const uint64_t divisor = static_cast<uint64_t>(kernel_size) * kernel_size;
    std::vector<uint32_t> horizontal(static_cast<size_t>(height) * width);
    pybind11::gil_scoped_release release;

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < height; ++y) {
        const auto* row = data + static_cast<size_t>(y) * stride;
        uint64_t sum = 0;
        for (int k = -radius; k <= radius; ++k) sum += row[clamp_index(k, width)];
        for (int x = 0; x < width; ++x) {
            horizontal[static_cast<size_t>(y) * width + x] = static_cast<uint32_t>(sum);
            if (x + 1 < width) {
                sum -= row[clamp_index(x - radius, width)];
                sum += row[clamp_index(x + radius + 1, width)];
            }
        }
    }

    #pragma omp parallel for schedule(static)
    for (int x = 0; x < width; ++x) {
        uint64_t sum = 0;
        for (int k = -radius; k <= radius; ++k) {
            sum += horizontal[static_cast<size_t>(clamp_index(k, height)) * width + x];
        }
        for (int y = 0; y < height; ++y) {
            data[static_cast<size_t>(y) * stride + x] = rounded_average(sum, divisor);
            if (y + 1 < height) {
                sum -= horizontal[static_cast<size_t>(clamp_index(y - radius, height)) * width + x];
                sum += horizontal[static_cast<size_t>(clamp_index(y + radius + 1, height)) * width + x];
            }
        }
    }
}

void sobel_edge(pybind11::array_t<uint8_t>& image) {
    const pybind11::buffer_info buf = image.request();
    if (buf.ndim != 2) throw std::invalid_argument("expected a 2D grayscale image");
    const int height = static_cast<int>(buf.shape[0]);
    const int width = static_cast<int>(buf.shape[1]);
    if (height == 0 || width == 0) return;

    auto* data = static_cast<uint8_t*>(buf.ptr);
    const int stride = static_cast<int>(buf.strides[0]);
    std::vector<uint32_t> magnitude_squared(static_cast<size_t>(height) * width);
    uint32_t max_squared = 0;
    pybind11::gil_scoped_release release;

    #pragma omp parallel for schedule(static) reduction(max:max_squared)
    for (int y = 0; y < height; ++y) {
        const int ym1 = clamp_index(y - 1, height), yp1 = clamp_index(y + 1, height);
        for (int x = 0; x < width; ++x) {
            const int xm1 = clamp_index(x - 1, width), xp1 = clamp_index(x + 1, width);
            const int p00 = data[static_cast<size_t>(ym1) * stride + xm1];
            const int p01 = data[static_cast<size_t>(ym1) * stride + x];
            const int p02 = data[static_cast<size_t>(ym1) * stride + xp1];
            const int p10 = data[static_cast<size_t>(y) * stride + xm1];
            const int p12 = data[static_cast<size_t>(y) * stride + xp1];
            const int p20 = data[static_cast<size_t>(yp1) * stride + xm1];
            const int p21 = data[static_cast<size_t>(yp1) * stride + x];
            const int p22 = data[static_cast<size_t>(yp1) * stride + xp1];
            const int gx = -p00 + p02 - 2 * p10 + 2 * p12 - p20 + p22;
            const int gy = -p00 - 2 * p01 - p02 + p20 + 2 * p21 + p22;
            const uint32_t squared = static_cast<uint32_t>(gx * gx + gy * gy);
            magnitude_squared[static_cast<size_t>(y) * width + x] = squared;
            max_squared = std::max(max_squared, squared);
        }
    }

    if (max_squared == 0) {
        #pragma omp parallel for schedule(static)
        for (int y = 0; y < height; ++y) {
            std::fill_n(data + static_cast<size_t>(y) * stride, width, uint8_t{0});
        }
        return;
    }
    const float scale = 255.0f / std::sqrt(static_cast<float>(max_squared));
    #pragma omp parallel for schedule(static)
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const float value = std::sqrt(static_cast<float>(magnitude_squared[static_cast<size_t>(y) * width + x])) * scale;
            data[static_cast<size_t>(y) * stride + x] = static_cast<uint8_t>(std::min(255.0f, value + 0.5f));
        }
    }
}

bool openmp_enabled() {
#ifdef _OPENMP
    return true;
#else
    return false;
#endif
}
int openmp_max_threads() {
#ifdef _OPENMP
    return omp_get_max_threads();
#else
    return 1;
#endif
}
}  // namespace image_processor
