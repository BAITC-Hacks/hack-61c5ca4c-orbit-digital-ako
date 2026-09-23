import {test, expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('cluster overview, keyboard alternative, dialog focus and both themes', async ({page,request}) => {
  const projects = await (await request.get('/api/projects')).json();
  const project = projects.find((p:any) => p.status === 'ready' && p.summary?.nodes === 2248);
  expect(project).toBeTruthy();
  const base = `/projects/${project.id}`;
  const errors:string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(base + '/investigate');
  await expect(page.locator('.graph-count')).toContainText('71');
  await expect(page.locator('.minimap circle')).toHaveCount(71);
  const points = await page.locator('.minimap circle').evaluateAll(nodes => nodes.map(n => [Number(n.getAttribute('cx')), Number(n.getAttribute('cy'))]));
  let minimum = Infinity;
  points.forEach((a,i) => points.slice(i+1).forEach(b => minimum = Math.min(minimum, Math.hypot(a[0]-b[0],a[1]-b[1]))));
  expect(minimum).toBeGreaterThan(5);
  const summary = page.locator('.graph-accessible summary');
  await summary.focus(); await page.keyboard.press('Enter');
  await expect(page.locator('.graph-accessible input')).toBeVisible();
  await page.locator('.graph-accessible input').fill('Кластер 1');
  const cluster = page.locator('.graph-accessible').getByRole('button',{name:'Кластер 1',exact:true});
  await cluster.focus(); await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/cluster=1/);
  await page.goto(base + '/overview');
  const search = page.locator('.command-button');
  await search.focus(); await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(search).toBeFocused();
  await page.locator('.sidebar-footer button').click();
  await page.getByRole('checkbox', {name:/Однобуквенные/}).uncheck();
  await page.keyboard.press('Escape');
  await page.keyboard.press('/');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.keyboard.press('Control+k');
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  for (const theme of ['light','dark']) {
    if (await page.locator('html').getAttribute('data-theme') !== theme) await page.getByRole('button',{name:'Theme',exact:true}).click();
    for (const route of ['overview','investigate','nodes','clusters','settings','cases','simulate','assistant']) {
      await page.goto(base + '/' + route);
      await page.waitForTimeout(350);
      const audit = await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']).analyze();
      expect(audit.violations, theme + '/' + route).toEqual([]);
    }
  }
  await page.getByRole('button',{name:'Theme',exact:true}).click();
  await page.goto(base + '/investigate');
  await page.screenshot({path:'../docs/screens/cluster-overview.png',fullPage:true});
  expect(errors).toEqual([]);
});
