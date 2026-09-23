import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
test("3000 nodes, offline resources, dark theme and accessibility audit", async ({
  page,
  request,
  baseURL,
}) => {
  const projects = await (await request.get("/api/projects")).json();
  let project = projects.find(
    (p: { name: string; status: string }) =>
      p.name === "Synthetic USD investigation" && p.status === "ready",
  );
  if (!project) {
    project = await (
      await request.post("/api/projects", {
        data: { name: "Synthetic USD investigation" },
      })
    ).json();
    const prefix = "/api/projects/" + project.id;
    for (const name of ["syn_en.csv", "seeds.csv"]) {
      const upload = await request.post(prefix + "/files", {
        multipart: {
          files: {
            name,
            mimeType: "text/csv",
            buffer: fs.readFileSync("../.local/synthetic/" + name),
          },
        },
      });
      expect(upload.ok()).toBe(true);
    }
    const previews = await (await request.get(prefix + "/preview")).json();
    const mapping = await request.put(prefix + "/mapping", {
      data: {
        currency: "USD",
        confirmed: true,
        files: previews.map((f: any) => ({
          file_id: f.id,
          kind: f.proposal.kind,
          fields: Object.fromEntries(
            Object.entries(f.proposal.fields).map(([k, v]: [string, any]) => [
              k,
              v.column,
            ]),
          ),
        })),
      },
    });
    expect(mapping.ok()).toBe(true);
    const job = await (await request.post(prefix + "/run")).json();
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/jobs/" + job.job_id)).json()).status,
        { timeout: 150000 },
      )
      .toBe("complete");
  }
  expect(project).toBeTruthy();
  const external: string[] = [];
  const appOrigin = new URL(baseURL as string).origin;
  page.on("request", (r) => {
    if (
      !r.url().startsWith("data:") &&
      !r.url().startsWith("blob:") &&
      new URL(r.url()).origin !== appOrigin
    )
      external.push(r.url());
  });
  await page.goto(`/projects/${project.id}/investigate?network=1&limit=3000`);
  await expect(page.locator(".graph-count")).toContainText("3");
  await expect(page.locator(".graph-canvas canvas").first()).toBeVisible();
  await page.waitForTimeout(5000);
  const response = await request.get(
    `/api/projects/${project.id}/network-graph?limit=3000`,
  );
  expect((await response.json()).nodes).toHaveLength(3000);
  const box = await page.locator(".graph-canvas").boundingBox();
  expect(box).toBeTruthy();
  const frames = page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const values: number[] = [];
        let previous = performance.now();
        const end = previous + 2500;
        function frame(now: number) {
          values.push(now - previous);
          previous = now;
          if (now < end) requestAnimationFrame(frame);
          else resolve(values);
        }
        requestAnimationFrame(frame);
      }),
  );
  await page.mouse.move(box!.x + 20, box!.y + 20);
  await page.mouse.down();
  for (let i = 0; i < 100; i++)
    await page.mouse.move(box!.x + 20 + i * 2, box!.y + 20 + i, { steps: 1 });
  await page.mouse.up();
  const timings = await frames;
  const fps = 1000 / (timings.reduce((a, b) => a + b, 0) / timings.length);
  const violations: Record<string, unknown> = {};
  for (const route of [
    "overview",
    "investigate?network=1&limit=3000",
    "nodes",
    "clusters",
    "settings",
    "cases",
    "simulate",
  ]) {
    await page.goto(`/projects/${project.id}/${route}`);
    await page.waitForTimeout(800);
    const result = await new AxeBuilder({ page }).analyze();
    violations[route] = result.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        summary: n.failureSummary,
      })),
    }));
    expect(result.violations.filter((v) => v.impact === "critical")).toEqual(
      [],
    );
  }
  await page.goto("/");
  await page.screenshot({
    path: test.info().outputPath("projects.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Theme", exact: true }).click();
  await page.screenshot({ path: test.info().outputPath("dark.png"), fullPage: true });
  await page.goto("/api/docs");
  await expect(page.locator(".swagger-ui")).toBeVisible();
  fs.writeFileSync(
    "../.local/browser-audit.json",
    JSON.stringify(
      { fps, frames: timings.length, external, violations },
      null,
      2,
    ),
  );
  expect(external).toEqual([]);
  expect(fps).toBeGreaterThanOrEqual(30);
});
