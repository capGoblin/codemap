import { expect, test, type Page } from "@playwright/test";
import { fixtureDetailLoader, fixtureGraph } from "../../src/dev/fixture";

// The preview server has no API, so answer the calls the page makes from the fixture.
async function openFixtureTrace(page: Page) {
  const id = fixtureGraph.trace.id;
  await page.route(`**/api/v1/traces/${id}?depth=99`, (r) => r.fulfill({ json: fixtureGraph }));
  await page.route(`**/api/v1/traces/${id}/nodes/*/detail`, async (r) => {
    const nodeId = decodeURIComponent(new URL(r.request().url()).pathname.split("/").at(-2)!);
    await r.fulfill({ json: await fixtureDetailLoader(id, nodeId) });
  });
  await page.goto(`/traces/${id}`);
}

test("fixture graph renders, is fitted, and opens a phase with one click", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await openFixtureTrace(page);
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

test("clicking a step shows its details; a Data touched row fades other nodes", async ({ page }) => {
  await openFixtureTrace(page);
  await expect(page.locator(".react-flow__node")).not.toHaveCount(0, { timeout: 5000 });
  await page.waitForTimeout(1000);
  await page.getByTestId("node-p2").click();
  await expect(page.getByTestId("node-p2.s2")).toBeVisible();
  await page.waitForTimeout(800);
  await page.getByTestId("node-p2.s2").click();
  const panel = page.getByTestId("details-tab");
  await expect(panel).toContainText("Save order");
  await expect(panel).toContainText("Create the order and add one row per item.");
  await expect(panel).toContainText("Code changed since this trace; snippet may not match.");
  await expect(page.getByTestId("code-view")).toContainText("db.session.commit()");

  // A cite moves the highlight to its lines.
  await panel.locator(".steps .cite").nth(1).click();
  await expect(page.locator(".code-line.hl-active")).toHaveCount(2);

  // "users" is only touched by p1 and its steps; p3 must fade. Click again to clear.
  await page.getByRole("button", { name: "Data touched" }).first().click();
  await page.getByTestId("target-db:users").click();
  await expect(page.getByTestId("node-p3")).toHaveCSS("opacity", "0.3");
  await expect(page.getByTestId("node-p1")).toHaveCSS("opacity", "1");
  await page.getByTestId("target-db:users").click();
  await expect(page.getByTestId("node-p3")).toHaveCSS("opacity", "1");
  await expect(page.getByTestId("effect-lane")).toHaveCount(0);
});

test("no card clips with every level open", async ({ page }) => {
  await openFixtureTrace(page);
  await expect(page.locator(".react-flow__node")).not.toHaveCount(0, { timeout: 5000 });
  await page.getByRole("button", { name: /expand all/i }).click();
  await expect(page.getByTestId("node-p2.s2.a")).toBeVisible({ timeout: 5000 });
  await page.waitForTimeout(800);
  const bad = await page.locator(".node-card").evaluateAll((cards) =>
    cards.filter((c) => c.scrollHeight > c.clientHeight + 1).map((c) => c.textContent),
  );
  expect(bad).toEqual([]);
});
