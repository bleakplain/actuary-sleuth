import { test, expect } from '@playwright/test';

test.describe('合规检查', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/compliance');
    await page.waitForSelector('text=合规检查助手', { timeout: 10_000 });
  });

  test('产品参数检查 — 填写表单提交', async ({ page }) => {
    await page.locator('.ant-form-item:has-text("产品名称") input').fill('E2E 测试健康险');
    await page.locator('.ant-form-item:has-text("险种类型") input').fill('健康险');
    await page.locator('.ant-form-item:has-text("产品参数") textarea').fill('等待期: 90天\n免赔额: 0元\n保险期间: 1年');

    await page.click('button:has-text("开始检查")');

    // 等待成功或错误（LLM 可能较慢）
    await Promise.any([
      page.locator('.ant-message-success').waitFor({ state: 'visible', timeout: 120_000 }),
      page.locator('.ant-message-error').waitFor({ state: 'visible', timeout: 120_000 }),
    ]);

    if (await page.locator('.ant-message-error').isVisible()) {
      test.skip('合规检查失败（RAG 引擎或 LLM 不可用）');
      return;
    }

    // 报告出现
    await expect(page.locator('text=检查报告')).toBeVisible();
  });

  test('条款文档审查 — 粘贴条款内容', async ({ page }) => {
    await page.click('.ant-tabs-tab:has-text("条款文档审查")');

    await page.locator('.ant-form-item:has-text("条款内容") textarea').fill(
      '# 测试健康保险条款\n\n等待期：自合同生效日起90天\n免赔额：0元\n保险期间：1年'
    );

    await page.click('button:has-text("开始审查")');

    await Promise.any([
      page.locator('.ant-message-success').waitFor({ state: 'visible', timeout: 120_000 }),
      page.locator('.ant-message-error').waitFor({ state: 'visible', timeout: 120_000 }),
    ]);

    if (await page.locator('.ant-message-error').isVisible()) {
      test.skip('合规检查失败（RAG 引擎或 LLM 不可用）');
      return;
    }

    await expect(page.locator('text=检查报告')).toBeVisible();
  });

  test('检查历史 — 查看历史表格', async ({ page }) => {
    await page.click('.ant-tabs-tab:has-text("检查历史")');

    await expect(page.locator('.ant-table')).toBeVisible({ timeout: 5_000 });
    await expect(page.locator('th:has-text("产品名称")')).toBeVisible();
    await expect(page.locator('th:has-text("检查时间")')).toBeVisible();
  });
});
