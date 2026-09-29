cmake_minimum_required(VERSION 3.15)
project(image_processor LANGUAGES CXX)
include(GNUInstallDirs)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Build type (default to Release if not specified)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

find_package(pybind11 CONFIG REQUIRED)

# Find OpenMP
find_package(OpenMP REQUIRED)

# Include directories
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/src)

# Source files
set(SOURCES
    src/image_processor.cpp
    src/pybind11_bindings.cpp
)

# Create the Python extension module
pybind11_add_module(image_processor ${SOURCES})

# Link OpenMP
target_link_libraries(image_processor PRIVATE OpenMP::OpenMP_CXX)

# Set output directory for the built module
set_target_properties(image_processor PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}
)

# Installation (optional)
install(TARGETS image_processor LIBRARY DESTINATION . RUNTIME DESTINATION .)
