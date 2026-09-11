import type { JSONContent } from "@tiptap/core";

export const emailFonts = { sans: "Arial, Helvetica, sans-serif", serif: "Georgia, 'Times New Roman', serif", modern: "Verdana, Geneva, sans-serif" };
export type EmailStyle = { background: string; buttonBackground: string; font: keyof typeof emailFonts; fontSize: number; radius: number };
export const defaultEmailStyle: EmailStyle = { background: "#ffffff", buttonBackground: "#d6f04a", font: "sans", fontSize: 16, radius: 6 };
export const stylePresets = [
  ["Белый", "#ffffff", "#d6f04a"], ["Кремовый", "#fff8e7", "#7c3b14"], ["Песочный", "#f3eadb", "#573f2d"],
  ["Мятный", "#eaf7ef", "#176443"], ["Голубой", "#edf5ff", "#1746a2"], ["Лавандовый", "#f2edff", "#633c91"],
  ["Розовый", "#fff0f3", "#9a2452"], ["Серый", "#f1f3f5", "#384354"],
  ["Белый на чёрном", "#000000", "#d6f04a"], ["Белый на синем", "#1746a2", "#ffffff"],
  ["Белый на красном", "#a71930", "#ffffff"], ["Белый на зелёном", "#145c40", "#ffffff"], ["Белый на фиолетовом", "#54278a", "#ffffff"],
] as const;
export function validColor(value: unknown): value is string { return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value); }
export function readableText(color: string): string {
  const channels = color.slice(1).match(/../g)!.map(part => { const c = parseInt(part, 16) / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722 > 0.179 ? "#000000" : "#ffffff";
}
export function getEmailStyle(state?: JSONContent): EmailStyle {
  const raw = state?.attrs?.emailStyle ?? {};
  return { background: validColor(raw.background) ? raw.background.toLowerCase() : defaultEmailStyle.background,
    buttonBackground: validColor(raw.buttonBackground) ? raw.buttonBackground.toLowerCase() : defaultEmailStyle.buttonBackground,
    font: Object.hasOwn(emailFonts, raw.font) ? raw.font : "sans", fontSize: [14, 16, 18, 20].includes(raw.fontSize) ? raw.fontSize : 16,
    radius: [0, 6, 12, 24].includes(raw.radius) ? raw.radius : 6 };
}
export function withEmailStyle(state: JSONContent, style: EmailStyle): JSONContent { return { ...state, attrs: { ...state.attrs, emailStyle: style } }; }

// Bounded RGB histogram; ignore transparent pixels and merge near-identical colours.
export function paletteFromPixels(pixels: Uint8ClampedArray): string[] {
  const bins = new Map<string, { count: number; sum: number[] }>();
  for (let i = 0; i < pixels.length; i += 4) {
    if (pixels[i + 3] < 128) continue;
    const rgb = [pixels[i], pixels[i + 1], pixels[i + 2]];
    const key = rgb.map(c => Math.floor(c / 32)).join(",");
    const bin = bins.get(key) ?? { count: 0, sum: [0, 0, 0] };
    bin.count++; rgb.forEach((c, j) => { bin.sum[j] += c; }); bins.set(key, bin);
  }
  const picked: number[][] = [];
  for (const bin of [...bins.values()].sort((a, b) => b.count - a.count)) {
    const rgb = bin.sum.map(sum => Math.round(sum / bin.count));
    if (picked.every(other => rgb.reduce((sum, c, j) => sum + (c - other[j]) ** 2, 0) > 48 ** 2)) picked.push(rgb);
    if (picked.length === 6) break;
  }
  return picked.map(rgb => "#" + rgb.map(c => c.toString(16).padStart(2, "0")).join(""));
}
