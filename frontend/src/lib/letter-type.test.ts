import { describe, expect, it } from "vitest";
import { generalLetterIssue, getLetterType, initialDocument, withLetterType } from "./mailing";

describe("letter type", () => {
  it("defaults legacy templates to personalized and preserves document data", () => {
    expect(getLetterType(initialDocument)).toBe("personalized");
    const state = { ...initialDocument, attrs: { custom: "kept" } };
    const general = withLetterType(state, "general");
    expect(getLetterType(general)).toBe("general");
    expect(general.content).toBe(state.content);
    expect(general.attrs?.custom).toBe("kept");
    expect(state.attrs).toEqual({ custom: "kept" });
    expect(getLetterType(withLetterType(general, "personalized"))).toBe("personalized");
  });
  it("allows a thematic heading and shared product without a name", () => {
    expect(generalLetterIssue({ type: "doc", content: [{ type: "heading", content: [{ type: "text", text: "Предложение {{product_name}}" }] }] }, "Новая услуга")).toBe("");
  });
  it("detects recipient fields in nodes, subject, CTA and complex expressions", () => {
    expect(generalLetterIssue(initialDocument, "")).toContain("{{first_name}}");
    for (const value of ["{{company}}", "{{custom_city}}", "{{ first_name | default('') }}", "{% if email %}x{% endif %}"]) {
      expect(generalLetterIssue({}, value)).not.toBe("");
      expect(generalLetterIssue({ content: [{ type: "ctaButton", attrs: { label: value, url: "https://example.com" } }] }, "")).not.toBe("");
    }
  });
});
