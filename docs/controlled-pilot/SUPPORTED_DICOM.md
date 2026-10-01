# Supported DICOM Matrix

This matrix is deliberately narrow. “Accepted” means eligible for the controlled evaluation only after automated validation succeeds.

| Capability | Pilot status | Required behavior |
|---|---|---|
| MR Image Storage, single-frame | Accepted | Explicit VR Little Endian or Implicit VR Little Endian; MONOCHROME1/2; valid rows, columns and pixel data |
| CT Image Storage, single-frame | Accepted | Same transfer syntax and pixel requirements as MR; rescale slope/intercept preserved |
| Uncompressed native pixel data | Accepted | Source bytes immutable and SHA-256 recorded |
| Signed/high-bit-depth pixels | Accepted with validation | Pixel representation, bits stored, high bit and rescale metadata must be internally consistent |
| Geometric stack ordering | Accepted with validation | Use image position and orientation; show warning when falling back to instance number |
| Pixel spacing | Optional | Measurements disabled when missing, invalid, or inconsistent |
| VOI window values / LUT | Accepted with validation | Preserve DICOM values; never bake changes into source data |
| Compressed transfer syntaxes | Not supported | Reject with transfer syntax and instance identifier; never silently decode/fallback |
| Enhanced MR/CT or multi-frame | Not supported | Reject explicitly |
| Secondary capture, ultrasound, XA, mammography, NM, PET | Not supported | Reject explicitly |
| Encapsulated PDF/SR/SEG/PR | Not supported | Reject explicitly |

## Series-level warnings

The viewer must expose duplicate SOP Instance UIDs, corrupt frames, inconsistent orientation or spacing, missing geometric position, nonuniform dimensions, and probable gaps. A warning cannot be converted into “normal,” “complete,” or “diagnostically adequate.”
