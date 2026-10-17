import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:net";
import path from "node:path";
import { expect, test } from "@playwright/test";

// Playwright runs from frontend/. No mocks: this spec runs against `codemap serve-dev` on a trace built by ScriptedModel.
const ROOT = path.resolve(process.cwd(), "..");
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
  graph = (await (await fetch(`${url}/api/v1/traces/${traceId}?depth=1`)).json()) as Graph;
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

test("open a phase, expand all, and read a step's code on the real server", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const phases = graph.nodes.filter((n) => n.level === 0);
  const steps = graph.nodes.filter((n) => n.level > 0);
  expect(phases.length).toBeGreaterThan(0);
  expect(steps.length).toBeGreaterThan(0);

  await page.goto(`${url}/traces/${traceId}`);
  const first = page.getByTestId(`node-${phases[0]!.id}`);
  await expect(first).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".banner-err")).toHaveCount(0);

  const width = () => first.evaluate((e) => (e.closest(".react-flow__node") as HTMLElement).offsetWidth);
  await page.waitForTimeout(1000); // let the first fit-all animation settle
  const before = await width();
  await first.click();
  const own = steps.find((s) => s.parent_id === phases[0]!.id)!;
  await expect(page.getByTestId(`node-${own.id}`)).toBeVisible({ timeout: 5000 });
  await expect.poll(width).toBeGreaterThan(before);

  await page.getByRole("button", { name: /expand all/i }).click();
  for (const s of steps) await expect(page.getByTestId(`node-${s.id}`)).toBeVisible({ timeout: 5000 });

  await page.waitForTimeout(800); // let the camera settle before clicking
  await page.getByTestId(`node-${steps[0]!.id}`).click();
  const panel = page.getByTestId("detail-panel");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("def ");
  expect(errors).toEqual([]);
});
