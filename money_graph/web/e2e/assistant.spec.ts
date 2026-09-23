import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("existing assistant: local evidence, graph links, selected CSV and no external requests", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  const external: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (
      !r.url().startsWith("http://127.0.0.1:8000") &&
      !/^(data|blob):/.test(r.url())
    )
      external.push(r.url());
  });
  const projects = await (await request.get("/api/projects")).json();
  let project = projects.find((p: { status: string }) => p.status === "ready");
  if (!project) {
    const demo = await (await request.post("/api/demo")).json();
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/jobs/" + demo.job_id)).json()).status,
        { timeout: 90000 },
      )
      .toBe("complete");
    project = { id: demo.project_id };
  }
  const prefix = "/api/projects/" + project.id;
  const top = await (await request.get(prefix + "/nodes?limit=1")).json();
  const gid = top.items[0].gid;
  await page.goto(
    `/projects/${project.id}/assistant?node=${encodeURIComponent(gid)}`,
  );
  await page
    .getByRole("button", { name: "Объяснить узлы", exact: true })
    .click();
  await expect(page.locator(".assistant-answer")).toContainText(gid);
  await expect(page.locator(".assistant-answer .status")).toHaveText(
    "Локальные инструменты",
  );
  const audit = await new AxeBuilder({ page }).analyze();
  expect(audit.violations).toEqual([]);
  await page.screenshot({
    path: "../docs/screens/assistant.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "Показать основания на графе" }).click();
  await expect(page).toHaveURL(/selection=/);
  await expect(page.locator(".graph-canvas canvas").first()).toBeVisible();
  await expect(page.locator(".node-id")).toBeVisible();
  await page.goto(`/projects/${project.id}/nodes`);
  await page.getByRole("checkbox", { name: gid, exact: true }).check();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Экспорт выбранных · CSV" }).click();
  expect((await download).suggestedFilename()).toBe("selected_nodes.csv");
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
});
