# Voxura Controlled Evaluation Pilot

## Intended use

Voxura is evaluation software for qualified healthcare professionals. The October 6 release may be used only in a supervised, single-site, on-premises evaluation with licensed, de-identified DICOM studies.

It supports review of accepted MR and CT image stacks, basic presentation controls, and evaluation notes. It does not provide diagnoses, diagnostic recommendations, automated reports, or report signing.

## Prohibited use

- Primary diagnosis, emergency care, treatment decisions, or replacement of PACS/RIS.
- Real patient data before written institutional privacy and security approval.
- AI-derived findings, normal/negative conclusions, or autonomous interpretation.
- Unsupported transfer syntaxes, enhanced or multi-frame objects, or modalities outside the supported-object matrix.
- Clinical use after any release gate is failed, waived, or cannot be evidenced.

## Mandatory user disclosure

> CONTROLLED EVALUATION ONLY — DE-IDENTIFIED DATA. Not validated for primary diagnosis, clinical reporting, treatment decisions, emergency use, or replacement of PACS/RIS.

The disclosure must remain visible in the worklist and viewer. A build without it is not release-eligible.

## Responsibility

The clinical evaluator remains responsible for patient/study identity checks, completeness, orientation, laterality, and comparison with the institution's approved diagnostic system. Voxura output must not be copied into a clinical record.
