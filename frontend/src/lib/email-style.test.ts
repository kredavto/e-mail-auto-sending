import { describe, expect, it } from "vitest";
import { defaultEmailStyle, getEmailStyle, paletteFromPixels, readableText, stylePresets, withEmailStyle } from "./email-style";

describe("email style", () => {
  it("keeps legacy templates usable and stores style without losing content or letter type", () => {
    expect(getEmailStyle()).toEqual(defaultEmailStyle);
    const state = { type: "doc", attrs: { letterType: "general" }, content: [{ type: "paragraph" }] };
    const styled = withEmailStyle(state, { ...defaultEmailStyle, background: "#1746a2" });
    expect(styled.content).toEqual(state.content);
    expect(styled.attrs?.letterType).toBe("general");
    expect(getEmailStyle(styled).background).toBe("#1746a2");
    expect(state.attrs).not.toHaveProperty("emailStyle");
  });
  it("uses white text for all contrast presets and black for light presets", () => {
    for (const [label, background] of stylePresets) expect(readableText(background)).toBe(label.startsWith("Белый на") ? "#ffffff" : "#000000");
  });
  it("does not accept arbitrary CSS in persisted style", () => {
    expect(getEmailStyle({ attrs: { emailStyle: { background: 'url(https://example.com)', font: '__proto__', fontSize: 999, radius: -1 } } })).toEqual(defaultEmailStyle);
  });
  it("extracts real dominant colours and ignores transparency", () => {
    expect(paletteFromPixels(new Uint8ClampedArray([255, 0, 0, 255, 255, 0, 0, 255, 0, 0, 255, 255, 0, 255, 0, 0]))).toEqual(["#ff0000", "#0000ff"]);
    expect(paletteFromPixels(new Uint8ClampedArray([0, 0, 0, 0]))).toEqual([]);
  });
});
