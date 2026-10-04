# Candidate reference sources for controlled-pilot acceptance

Reviewed 4 October 2026. These are **candidate sources**, not approved Voxura fixtures, appointed reviewers, accepted licenses, or completed release gates. No data was downloaded or imported during this review.

| Source | Verified content and fit | Remaining condition |
| --- | --- | --- |
| [TCIA NSCLC-Radiomics](https://www.cancerimagingarchive.net/collection/nsclc-radiomics/) | CT images are DICOM; the collection includes SEG and RTSTRUCT annotations and is listed as CC BY-NC 3.0. A subset of supported single-frame, uncompressed CT instances may be useful for technical viewer checks. TCIA notes missing slices in several cases. | Site data custodian must approve exact series, permitted use, de-identification review, hashes, and independent pixel/geometry/measurement references. SEG/RTSTRUCT are outside the current viewer allowlist. |
| [TCIA TCGA-GBM](https://www.cancerimagingarchive.net/collection/tcga-gbm/) | MR/CT/DX DICOM collection. TCIA warns that some images may permit facial reconstruction and lists NIH Controlled Data Access Policy. | Do not retrieve or use until access is approved, cases are screened, and a data custodian approves handling. Select only supported MR objects and independent references. |
| [NYU fastMRI](https://fastmri.med.nyu.edu/) | Provides de-identified raw k-space and some DICOM MR data. Dataset agreement limits use to internal research/education and requires individual application and agreement; it says data are not for clinical use. | Authorized institution/user must obtain access and determine whether the planned evaluation is permitted. Raw k-space is not DICOM viewer input. No agreement has been accepted for Voxura. |
| [SynthRAD2023 design record](https://zenodo.org/records/7781049) and [dataset record](https://zenodo.org/records/7260705) | The supplied record is a challenge design PDF, not image data. The linked training dataset contains MR/CT image pairs as compressed NIfTI and describes a CC BY-NC 4.0 license. | NIfTI is outside the current DICOM allowlist. Use only for separately scoped research or an approved, validated conversion workflow; conversion cannot establish native DICOM display acceptance. Approve license/use before any retrieval. |
| [UK Biobank access](https://www.ukbiobank.ac.uk/use-our-data/apply-for-access/) | Controlled research access and institutional agreement are required. The official site says new applications are currently paused, with intended resumption in late 2026. | Not a practical source for the October 6 pilot without existing approved access and project-specific permission. |

The people named in source publications or dataset governance are **not automatically Voxura clinical reviewers or data custodians**. Attribution, investigator status, and hosting roles do not establish their consent to review this product. The site must appoint its own named clinical reviewer, data custodian, identity/security owner, operations owner, and release decision owner. Record their approval and scope in the release evidence without implying endorsement by source investigators.

## User-nominated reference contacts

The project owner nominated the following people or groups on 4 October 2026. Their status is **proposed and unconfirmed**. No one below has been contacted, accepted a Voxura role, obtained product access, or signed a release decision. These names are retained as leads for the client to verify, not as reviewers of record.

| Source area | Proposed clinical/reference contacts | Proposed custodian contact |
| --- | --- | --- |
| TCIA NSCLC-Radiomics / TCGA | Hugo Aerts, Philippe Lambin, Kenneth Aldape | Justin Kirby, Fred Prior |
| NYU fastMRI | Michael P. Recht, Yvonne W. Lui | NYU CAI2R |
| SynthRAD2023 | Matteo Maspero, Cornelis A. T. van den Berg | UMC Utrecht Radiotherapy / Grand Challenge |
| UK Biobank | Stephen Smith, Stefan Neubauer | UK Biobank Access Management Team |

An institution administrator can add proposed reviewers through the Voxura reviewer directory. It is institution-scoped and does not grant authentication roles or change formal gate status. Confirmed appointment and actual acceptance evidence require a separate site process.

## Minimum accepted-fixture record

For each selected collection and exact study/series: source URL and version/DOI, access agreement or license decision made by the authorized party, permitted Voxura use, data custodian approval, de-identification and burned-in-text review, modality/SOP class/transfer syntax/frame count, SHA-256 for each source object, independent reference renderer and version, expected pixel/rescale/VOI/ordering/orientation/spacing/measurement results, numerical tolerances, reviewer name and signed decision. Keep images and any sensitive metadata outside source control.

Current recommendation: assess a narrow NSCLC-Radiomics CT subset first for compatibility, then an independently approved MR DICOM subset. This is a prioritization for review, not authorization to download or a formal gate PASS. All seven formal release gates remain NOT RUN and the decision remains NO-GO.
