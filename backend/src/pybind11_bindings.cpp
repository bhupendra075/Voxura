#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include "image_processor.hpp"

namespace py = pybind11;

namespace {
py::array_t<uint8_t> require_image(py::array image) {
    if (!py::isinstance<py::array_t<uint8_t>>(image)) throw py::type_error("image must have dtype uint8");
    if ((image.flags() & py::array::c_style) == 0) throw py::value_error("image must be C-contiguous");
    if (!image.writeable()) throw py::value_error("image must be writable");
    if (image.ndim() != 2) throw py::value_error("image must be a 2D grayscale array");
    return py::reinterpret_borrow<py::array_t<uint8_t>>(image);
}
}  // namespace

PYBIND11_MODULE(image_processor, module) {
    module.doc() = "High-performance, in-place grayscale processing with OpenMP";
    module.def("box_blur", [](py::array image, int kernel_size) {
        auto typed = require_image(std::move(image));
        image_processor::box_blur(typed, kernel_size);
    }, py::arg("image").noconvert(), py::arg("kernel_size") = 3);
    module.def("sobel_edge", [](py::array image) {
        auto typed = require_image(std::move(image));
        image_processor::sobel_edge(typed);
    }, py::arg("image").noconvert());
    module.def("openmp_enabled", &image_processor::openmp_enabled);
    module.def("openmp_max_threads", &image_processor::openmp_max_threads);
}
