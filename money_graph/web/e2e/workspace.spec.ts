import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import path from "node:path";
test("demo workspace: trace, graph, simulation, dossier, URL and accessibility", async ({
  page,
  context,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", {
      name: "От переводов — к проверяемой гипотезе",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Открыть пример" }).click();
  await expect(page).toHaveURL(/\/overview$/, { timeout: 90000 });
  const pid = page.url().split("/projects/")[1].split("/")[0];
  await page.screenshot({
    path: test.info().outputPath("overview.png"),
    fullPage: true,
  });
  const top = await (
    await request.get(`/api/projects/${pid}/nodes?limit=1`)
  ).json();
  const id = top.items[0].gid;
  await page.getByRole("link", { name: id, exact: true }).click();
  await expect(page.locator(".node-id")).toHaveText(id);
  await expect(page.locator(".graph-canvas canvas").first()).toBeVisible();
  await page.getByRole("tab", { name: "Почему эта роль" }).click();
  await expect(page.locator(".trace-rule.matched")).toBeVisible();
  await page.waitForTimeout(2500);
  await page.screenshot({
    path: test.info().outputPath("investigate.png"),
    fullPage: true,
  });
  await page
    .locator(".inspector")
    .getByRole("button", { name: "В блокировку" })
    .click();
  await page
    .locator(".inspector")
    .getByRole("button", { name: "В дело", exact: true })
    .click();
  const copy = await context.newPage();
  await copy.goto(page.url());
  await expect(copy.locator(".node-id")).toHaveText(id);
  await copy.close();
  await page.keyboard.press("Control+k");
  await page.getByRole("dialog").getByRole("textbox").fill(id.slice(-6));
  await expect(page.locator(".command-results")).toContainText(id);
  await page.keyboard.press("Escape");
  let axe = await new AxeBuilder({ page }).analyze();
  expect(axe.violations.filter((v) => v.impact === "critical")).toEqual([]);
  await page.getByRole("link", { name: "Симуляция", exact: true }).click();
  await expect(page.locator(".simulation-result")).toBeVisible();
  await page.getByRole("button", { name: "Сохранить сценарий в дело" }).click();
  await page.screenshot({
    path: test.info().outputPath("simulation.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Дело", exact: true }).click();
  await page.getByLabel("Название проекта").fill("Проверка гипотезы");
  await page
    .getByLabel("Заметки аналитика")
    .fill("Проверить входящие вне выборки.");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(page.locator(".saved-case")).toContainText("Проверка гипотезы");
  const report = page
    .getByRole("link", { name: "Открыть досье для печати" })
    .last();
  const href = await report.getAttribute("href");
  const response = await request.get(href!);
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain("Трассировка правил");
  await page.screenshot({ path: test.info().outputPath("cases.png"), fullPage: true });
  for (const [link, file] of [
    ["Узлы", "nodes"],
    ["Кластеры", "clusters"],
    ["Правила", "settings"],
  ]) {
    await page.getByRole("link", { name: link, exact: true }).click();
    await page.waitForTimeout(1500);
    await page.screenshot({
      path: test.info().outputPath(`${file}.png`),
      fullPage: true,
    });
  }
  await page.goto(`/projects/${pid}/overview`);
  await page.setViewportSize({ width: 420, height: 900 });
  await page.screenshot({ path: test.info().outputPath("mobile.png"), fullPage: true });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("new project -> CSV and seed mapping -> analysis -> dossier", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page
    .getByRole("button", { name: "Новый анализ", exact: true })
    .first()
    .click();
  await page.getByLabel("Название проекта").fill("Synthetic USD investigation");
  await page
    .getByRole("button", { name: "Создать проект", exact: true })
    .click();
  await page
    .locator("input[type=file]")
    .setInputFiles([
      path.resolve("../.local/synthetic/syn_en.csv"),
      path.resolve("../.local/synthetic/seeds.csv"),
    ]);
  await expect(page.locator(".file-row")).toHaveCount(2);
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await expect(page.locator(".mapping-card")).toHaveCount(2);
  await page.screenshot({
    path: test.info().outputPath("mapping.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await page.getByLabel("Валюта", { exact: true }).fill("USD");
  await page
    .getByRole("button", { name: "Подтвердить колонки и проверить данные" })
    .click();
  await expect(
    page.getByRole("button", { name: "Запустить анализ", exact: true }),
  ).toBeEnabled();
  await page.screenshot({
    path: test.info().outputPath("quality.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Запустить анализ", exact: true })
    .click();
  await expect(page).toHaveURL(/\/overview$/, { timeout: 150000 });
  await expect(page.locator(".kpi-grid")).toContainText("$");
  await page.locator(".top-table .id-link").first().click();
  await page.getByRole("tab", { name: "Почему эта роль" }).click();
  await expect(page.locator(".trace-rule.matched")).toBeVisible();
  await page
    .locator(".inspector")
    .getByRole("button", { name: "В блокировку" })
    .click();
  await page
    .locator(".inspector")
    .getByRole("button", { name: "В дело", exact: true })
    .click();
  await page.getByRole("link", { name: "Симуляция", exact: true }).click();
  await expect(page.locator(".simulation-result")).toBeVisible();
  await page.getByRole("link", { name: "Дело", exact: true }).click();
  await page.getByLabel("Название проекта").fill("Synthetic case");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Открыть досье для печати" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
