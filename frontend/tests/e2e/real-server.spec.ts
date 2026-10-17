import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:net";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Playwright runs from frontend/. No mocks: this spec runs against `codemap serve-dev` on a trace built by ScriptedModel.
const ROOT = path.resolve(process.cwd(), "..");
// Set SHOTS_DIR to save the review screenshots.
const SHOTS = process.env.SHOTS_DIR;
const STATIC = path.join(ROOT, "src/codemap/server/static");

type Graph = { nodes: { id: string; level: number; parent_id: string | null }[] };
let server: ChildProcess | undefined;
let url = "";
let traceId = "";
let graph: Graph;

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address() as { port: number };
      s.close(() => resolve(port));
    });
    s.on("error", reject);
  });
}

test.beforeAll(async () => {
  const out = execFileSync("uv", ["run", "python", "tests/fixtures/build_ui_fixture.py"], {
    cwd: ROOT,
    encoding: "utf8",
  });
  const fx = JSON.parse(out.trim().split("\n").at(-1)!) as { repo: string; trace_id: string };
  traceId = fx.trace_id;
  const port = await freePort();
  url = `http://127.0.0.1:${port}`;
  server = spawn(
    "uv",
    ["run", "codemap", "--repo", fx.repo, "serve-dev", "--port", String(port), "--static", STATIC],
    { cwd: ROOT, stdio: "inherit", detached: true },
  );
  for (let i = 0; ; i++) {
    try {
      if ((await fetch(`${url}/api/v1/health`)).ok) break;
    } catch {
      // Not up yet.
    }
    if (i > 100) throw new Error("serve-dev did not start");
    await new Promise((r) => setTimeout(r, 100));
  }
  graph = (await (await fetch(`${url}/api/v1/traces/${traceId}?depth=99`)).json()) as Graph;
});

test.afterAll(() => {
  // Kill the whole group: `uv run` spawns the real server as a child.
  if (server?.pid) {
    try {
      process.kill(-server.pid, "SIGTERM");
    } catch {
      // Already gone.
    }
  }
});

// Every card must show its whole text: no clipped content, title and summary inside the box.
async function expectNoClipping(page: Page) {
  const bad = await page.locator(".node-card").evaluateAll((cards) =>
    cards.flatMap((card) => {
      const box = card.getBoundingClientRect();
      const out: string[] = [];
      if (card.scrollHeight > card.clientHeight + 1) out.push(`${card.textContent}: scrollHeight`);
      for (const part of card.querySelectorAll(".nc-title, .nc-summary")) {
        const r = part.getBoundingClientRect();
        if (r.bottom > box.bottom + 1 || r.right > box.right + 1) out.push(`${part.textContent}: outside`);
      }
      return out;
    }),
  );
  expect(bad).toEqual([]);
}

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

test.use({ colorScheme: "dark", viewport: { width: 1500, height: 900 } });

test("open a phase, a child, read the details, and use Data touched on the real server", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const phases = graph.nodes.filter((n) => n.level === 0);
  const withKids = graph.nodes.find((n) => n.level === 1 && graph.nodes.some((k) => k.parent_id === n.id))!;
  const phase = phases.find((p) => p.id === withKids.parent_id)!;
  const sub = graph.nodes.find((n) => n.parent_id === withKids.id)!;
  expect(graph.nodes.some((n) => n.level === 2)).toBe(true);

  await page.goto(`${url}/traces/${traceId}`);
  const first = page.getByTestId(`node-${phase.id}`);
  await expect(first).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".banner-err")).toHaveCount(0);
  await page.waitForTimeout(1000); // let the first fit-all animation settle
  await expectNoClipping(page);
  await shot(page, "1-overview");

  // Open a phase in place: it grows and shows its steps.
  const width = () => first.evaluate((e) => (e.closest(".react-flow__node") as HTMLElement).offsetWidth);
  const before = await width();
  await first.click();
  await expect(page.getByTestId(`node-${withKids.id}`)).toBeVisible({ timeout: 5000 });
  await expect.poll(width).toBeGreaterThan(before);
  await page.waitForTimeout(800);

  // Open a child: the third level appears inside it.
  await page.getByTestId(`node-${withKids.id}`).click();
  await expect(page.getByTestId(`node-${sub.id}`)).toBeVisible({ timeout: 5000 });
  await page.waitForTimeout(800);
  await expectNoClipping(page);
  await shot(page, "2-opened-phase-and-child");

  // Details: How it works, code, and a cite that highlights its lines.
  const panel = page.getByTestId("details-tab");
  await expect(panel).toContainText("How it works");
  await expect(panel.locator(".steps li").first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("code-view")).toContainText("def ");
  await expect(page.locator(".code-line.hl-active")).toHaveCount(0);
  await panel.locator(".steps .cite").first().click();
  await expect(page.locator(".code-line.hl-active").first()).toBeVisible();
  await shot(page, "3-details");

  // Data touched: click a row, others fade; click again, they return.
  await page.getByRole("button", { name: "Data touched" }).first().click();
  const rows = page.locator(".dt-row");
  await expect(rows.first()).toBeVisible();
  await expect(page.locator(".dt-row .ph").first()).toContainText(/^[RW] /);
  await rows.first().click();
  await expect.poll(() => page.locator(".card-wrap").evaluateAll((els) => els.some((e) => (e as HTMLElement).style.opacity === "0.3"))).toBe(true);
  await shot(page, "4-data-touched");
  await rows.first().click();
  await expect.poll(() => page.locator(".card-wrap").evaluateAll((els) => els.some((e) => (e as HTMLElement).style.opacity === "0.3"))).toBe(false);

  // Expand all opens every level; collapse all closes them.
  await page.getByRole("button", { name: /expand all/i }).click();
  await expect(page.getByTestId(`node-${sub.id}`)).toBeVisible({ timeout: 5000 });
  await page.waitForTimeout(800);
  await expectNoClipping(page);
  await page.getByRole("button", { name: /collapse all/i }).click();
  await expect(page.getByTestId(`node-${sub.id}`)).toHaveCount(0);
  expect(await page.getByTestId("effect-lane").count()).toBe(0);
  expect(errors).toEqual([]);
});
