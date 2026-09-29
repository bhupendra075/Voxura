<<<<<<< HEAD
⚡ High-Performance Image Processor

A full-stack, hardware-accelerated image processing pipeline that bridges a blazing-fast C++ / OpenMP backend with a modern React frontend via FastAPI.

This project solves a classic engineering problem: standard Python is too slow for heavy pixel math, and C++ is too complex for rapid web API development. By combining the two using zero-copy memory mapping, this architecture achieves native C++ execution speeds while maintaining a scalable, user-friendly web interface.

🚀 Key Technical Highlights

Zero-Copy Memory Efficiency (Pybind11): Instead of copying large image buffers between Python and C++, the C++ engine uses Pybind11 buffer protocols (py::buffer_info) to read and write directly to the NumPy array's physical memory space. This eliminates serialization overhead and drastically reduces RAM usage.

Maximum CPU Core Utilization (OpenMP): By dropping into C++ and applying #pragma omp parallel for, pixel-level loops (like convolution kernels) are split into chunks and processed simultaneously across every available CPU core, bypassing Python's Global Interpreter Lock (GIL).

Decoupled Architecture: The system maintains strict separation of concerns. The C++ engine handles pure mathematics, the FastAPI layer handles HTTP transport, and the React frontend provides a responsive, interactive user experience.

📊 Performance Benchmarks

The following table demonstrates the massive performance gains achieved by moving pixel-level mathematics from high-level Python into a parallelized C++ environment.

Tested on a 4K Resolution Image (3840 x 2160) using an 8-Core CPU:
<img width="1020" height="144" alt="image" src="https://github.com/user-attachments/assets/fea029d0-908d-4a6f-a445-3a6528721a85" />

Note: Exact execution times will vary based on hardware, available CPU cores, and memory bandwidth, but the relative scaling efficiency remains consistent.

🌍 Real-World Applications

While built as a technical showcase, this architecture is directly applicable to fields requiring high-speed visual computing on constrained hardware:

Medical Diagnostics: Algorithms like the included Sobel Edge Detection are fundamental in isolating tumors or bone fractures in uncompressed X-rays. The multi-threaded backend allows resource-constrained rural clinics to process high-resolution medical scans in seconds on older hardware.

Digital Sustainability: Highly optimized, parallelized code requires less CPU time to achieve the same result, reducing overall energy consumption and compute costs at scale.

🛠️ Tech Stack

Core Engine: C++, OpenMP

Bindings & Memory: Pybind11, NumPy, OpenCV (for decoding)

Web API: Python, FastAPI, Uvicorn

Frontend: React, Vite, Tailwind CSS

🔀 Data Flow Architecture

Client (React): User uploads an image and selects a filter (e.g., Box Blur 15x15). Sent as FormData.

Server (FastAPI): Receives the byte stream, decodes it into a NumPy array, and passes the memory pointer to the native extension.

Engine (C++): Multi-threads the convolution matrix across the image using OpenMP, writing the results into a new aligned memory buffer.

Response: FastAPI encodes the modified buffer back to JPEG and returns it alongside high-resolution execution telemetry (X-Processing-Time-Ms).

💻 Installation & Setup

Prerequisites

C++ Compiler: GCC/Clang (Linux/Mac) or MSVC (Windows) with OpenMP support.

CMake: Version 3.14 or higher.

Python: 3.8+

Node.js: v18+

1. Build the C++ Backend & Start the API

Open your terminal in the project root and run:

# Navigate to backend

cd backend

# Create and activate a virtual environment

python -m venv .venv
.\.venv\Scripts\Activate.ps1 # (On Linux/Mac use: source .venv/bin/activate)

# Install dependencies (FastAPI, Pybind11, NumPy, OpenCV, etc.)

pip install -r requirements.txt

# Compile the C++ extension using CMake

mkdir build
cd build
cmake ..
cmake --build . --config Release
cd ..

# Start the FastAPI server

uvicorn app:app --host 127.0.0.1 --port 8000 --reload

The API will be available at http://127.0.0.1:8000/process

2. Start the React Frontend

Open a second terminal window:

# Navigate to frontend

cd frontend

# Install Node dependencies

npm install

# Start the Vite development server

npm run dev

Open your browser to http://localhost:5173 to use the dashboard.

🔌 API Reference

You can also bypass the UI and use the engine directly via CLI:

POST /process

curl -X POST "[http://127.0.0.1:8000/process](http://127.0.0.1:8000/process)" \
 -H "accept: image/jpeg" \
 -H "Content-Type: multipart/form-data" \
 -F "file=@your_test_image.jpg" \
 -F "filter_type=sobel" \
 -F "kernel_size=3" -o output.jpg

👨‍💻 Author

Bhupendra Suthar Software Developer | C++ | Python | React | Computer Vision

# GitHub

# High-Performance Image Processor

A FastAPI service and React interface for grayscale box blur and Sobel processing. The preferred backend is a zero-copy pybind11 extension using OpenMP; OpenCV and NumPy are development fallbacks.

## Backend

Use Python 3.10+ with a C++17 compiler and OpenMP. From `backend`:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[opencv,test]"
.\.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
=======
```

Set `PROCESSOR_REQUIRE_NATIVE=1` in production so startup fails instead of silently using a fallback. Other controls are `PROCESSOR_MAX_UPLOAD_BYTES`, `PROCESSOR_MAX_DIMENSION`, `PROCESSOR_MAX_MEGAPIXELS`, `PROCESSOR_MAX_KERNEL_SIZE`, `PROCESSOR_MAX_CONCURRENCY`, and `PROCESSOR_ALLOWED_ORIGINS`. Coordinate `PROCESSOR_MAX_CONCURRENCY` with `OMP_NUM_THREADS` so their product does not exceed the available CPU cores.

The v2 endpoints are `POST /v2/process` and `GET /v2/capabilities`. The legacy `POST /process` adapter is deprecated and has a sunset date of December 31, 2026.

## Frontend

From `frontend`:

```powershell
npm ci
npm run dev
npm run typecheck
npm run lint
npm test
```

Set `VITE_API_BASE_URL` when the API is not served from `http://localhost:8000`.

## Verification and benchmarks

From `backend`, run `python -m pytest`. Native parity tests skip when the extension is unavailable.

Run `python benchmarks/run.py` for the deterministic 512²–4096² benchmark. It performs warmups, reports median and p95 processing time, checks bounded concurrent throughput, and prints JSON without changing repository files. Use `--output benchmark-report.json` only when saving a local report. The report schema is stable at version 1; compare matching backend/filter/size/kernel rows when establishing regression thresholds.

> > > > > > > ba08adb7 (Improve image processor application)
