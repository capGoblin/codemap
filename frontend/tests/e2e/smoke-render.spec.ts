import { expect, test } from "@playwright/test";

test("fixture graph renders nodes", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/");
  await expect(page.locator(".react-flow__node")).not.toHaveCount(0, { timeout: 5000 });
  expect(await page.locator(".react-flow__node").count()).toBeGreaterThanOrEqual(3);
  await expect(page.locator(".banner-err")).toHaveCount(0);
  expect(errors).toEqual([]);
});
