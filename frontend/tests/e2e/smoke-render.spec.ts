import { expect, test } from "@playwright/test";

test("fixture graph renders, is fitted, and opens a phase with one click", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/");
  const nodes = page.locator(".react-flow__node");
  await expect(nodes).not.toHaveCount(0, { timeout: 5000 });
  expect(await nodes.count()).toBeGreaterThanOrEqual(3);
  await expect(page.locator(".banner-err")).toHaveCount(0);

  // Wait for the fit-all (400 ms animation) to settle, then check the view is centred.
  await page.waitForTimeout(1000);
  const view = (await page.locator(".react-flow").boundingBox())!;
  const boxes = await nodes.evaluateAll((els) =>
    els.map((e) => {
      const r = e.getBoundingClientRect();
      return { l: r.left, t: r.top, r: r.right, b: r.bottom };
    }),
  );
  const cx = (Math.min(...boxes.map((b) => b.l)) + Math.max(...boxes.map((b) => b.r))) / 2;
  const cy = (Math.min(...boxes.map((b) => b.t)) + Math.max(...boxes.map((b) => b.b))) / 2;
  expect(Math.abs(cx - (view.x + view.width / 2))).toBeLessThan(view.width * 0.15);
  expect(Math.abs(cy - (view.y + view.height / 2))).toBeLessThan(view.height * 0.15);

  // ONE click opens the phase.
  await page.getByTestId("node-p1").click();
  await expect(page.getByTestId("node-p1.s1")).toBeVisible({ timeout: 3000 });
  expect(errors).toEqual([]);
});
