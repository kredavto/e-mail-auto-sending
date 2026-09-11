import { expect, test } from "@playwright/test";

test("studio sidebar keeps readable text and does not overlap the editor", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const sidebar = page.locator(".studio-sidebar");
  const buttons = sidebar.getByRole("button");
  for (const width of [1440, 1101, 1024, 768, 540, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await sidebar.scrollIntoViewIfNeeded();
    await expect(buttons).toHaveCount(4);
    await expect(sidebar.locator(".sidebar-heading small")).toHaveCSS("font-size", "21px");
    for (const button of await buttons.all()) {
      await expect(button).toHaveCSS("font-size", "16px");
      await expect(button.locator("small")).toBeVisible();
      await expect(button.locator("small")).toHaveCSS("font-size", "13px");
      expect(await button.evaluate(el => el.scrollWidth <= el.clientWidth)).toBeTruthy();
    }
    const panelBox = (await sidebar.boundingBox())!;
    const contentBox = (await page.locator(".studio-content").boundingBox())!;
    if (width > 1100) {
      expect(panelBox.width).toBe(300);
      expect(panelBox.x + panelBox.width).toBeLessThan(contentBox.x);
      await expect(sidebar.locator(".sidebar-note small")).toHaveCSS("font-size", "14px");
    } else {
      expect(panelBox.y + panelBox.height).toBeLessThan(contentBox.y);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    if (width === 1440 || width === 320) {
      await sidebar.screenshot({ path: info.outputPath(`sidebar-${width}.png`) });
    }
  }
  await page.setViewportSize({ width: 1440, height: 600 });
  await buttons.last().focus();
  await expect(buttons.last()).toBeInViewport();
  await buttons.last().press("Enter");
  await expect(buttons.last()).toHaveAttribute("aria-current", "page");
  expect(errors).toEqual([]);
});
