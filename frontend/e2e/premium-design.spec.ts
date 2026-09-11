import { expect, test } from "@playwright/test";

test("premium shell: parallax, motion preference, accessible navigation and intact draft", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://fonts.googleapis.com/**", r => r.abort());
  await page.route("https://fonts.gstatic.com/**", r => r.abort());
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Ваши письма.");
  const hero = page.locator(".studio-hero");
  const motion = page.getByRole("button", { name: "Анимация интерфейса" });
  await expect(motion).toHaveAttribute("aria-pressed", "true");
  if (info.project.name === "desktop") {
    const bounds = (await hero.boundingBox())!;
    await page.mouse.move(bounds.x + 50, bounds.y + 80);
    await expect.poll(() => hero.evaluate(el => el.style.getPropertyValue("--parallax-x"))).not.toBe("0px");
    const before = await hero.evaluate(el => el.style.getPropertyValue("--parallax-y"));
    await page.evaluate(() => window.scrollTo({ top: 140, behavior: "instant" }));
    await expect.poll(() => hero.evaluate(el => el.style.getPropertyValue("--parallax-y"))).not.toBe(before);
  }
  await motion.click();
  await expect(motion).toHaveAttribute("aria-pressed", "false");
  await expect.poll(() => hero.evaluate(el => el.style.getPropertyValue("--parallax-x"))).toBe("0px");
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.locator(".studio-intro").screenshot({ path: info.outputPath("premium-hero.png") });
  await page.reload();
  await expect(motion).toHaveAttribute("aria-pressed", "false");
  await motion.click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(motion).toBeDisabled();
  await expect(motion).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".letter-front")).toHaveCSS("animation-name", "none");
  await page.getByRole("link", { name: "Перейти в студию", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Разделы приложения" })).toBeInViewport();
  await page.getByRole("button", { name: "Общее", exact: true }).click();
  await page.locator(".tiptap").fill("Несохранённый черновик — сохранить при переходах");
  await page.getByRole("button", { name: "Белый на синем", exact: false }).click();
  await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
  await page.getByRole("button", { name: /^Редактор письма/ }).click();
  await expect(page.locator(".tiptap")).toContainText("Несохранённый черновик");
  await expect(page.locator(".email-canvas")).toHaveCSS("background-color", "rgb(23, 70, 162)");
  await expect(page.locator(".email-canvas")).toHaveCSS("color", "rgb(255, 255, 255)");
  await page.locator("#studio").scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("premium-workspace.png") });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  if (info.project.name === "mobile") {
    await page.setViewportSize({ width: 320, height: 740 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  }
  expect(errors).toEqual([]);
});
