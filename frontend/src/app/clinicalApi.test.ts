import { describe, expect, it } from "vitest";
import { isReviewChecklistComplete } from "./clinicalApi";

describe("radiologist review checklist", () => {
  it("blocks review until every safety check is complete", () => {
    expect(isReviewChecklistComplete({
      patient_identity_confirmed: true, laterality_checked: true, priors_checked: true,
      critical_findings_checked: true, warnings_resolved: false,
    })).toBe(false);
  });

  it("allows the reviewed-not-signed transition when all checks are complete", () => {
    expect(isReviewChecklistComplete({
      patient_identity_confirmed: true, laterality_checked: true, priors_checked: true,
      critical_findings_checked: true, warnings_resolved: true,
    })).toBe(true);
  });
});
