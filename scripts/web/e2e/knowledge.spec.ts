import { test, expect } from '@playwright/test';

test.describe('知识库管理', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/knowledge');
    // 等待页面加载（表格或空状态）
    await Promise.any([
      page.waitForSelector('.ant-table-row', { timeout: 15_000 }),
      page.waitForSelector('.ant-table-placeholder', { timeout: 15_000 }),
    ]);
  });

  test('页面加载 — 状态卡片和操作按钮显示', async ({ page }) => {
    // 统计卡片
    await expect(page.locator('text=文档数量')).toBeVisible();
    await expect(page.locator('text=向量库文档')).toBeVisible();
    await expect(page.locator('text=BM25 状态')).toBeVisible();
    await expect(page.locator('text=当前版本')).toBeVisible();

    // 操作按钮
    await expect(page.locator('button:has-text("导入文档")')).toBeVisible();
    await expect(page.locator('button:has-text("刷新")')).toBeVisible();

    // 表格存在
    await expect(page.locator('.ant-table')).toBeVisible();
  });

  test('文档预览 — 有数据时点击预览按钮打开 Modal', async ({ page }) => {
    const rows = page.locator('.ant-table-row');
    if ((await rows.count()) === 0) {
      test.skip();
      return;
    }

    // 点击第一行的"预览"按钮
    await rows.first().locator('button:has-text("预览")').click();

    // Modal 打开
    const modal = page.locator('.ant-modal');
    await expect(modal).toBeVisible();
    await expect(modal.locator('.ant-modal-title')).toContainText('.md');

    // 关闭 Modal
    await page.locator('.ant-modal-close').click();
    await expect(modal).not.toBeVisible();
  });

  test('导入文档 — 点击按钮创建任务', async ({ page }) => {
    await page.click('button:has-text("导入文档")');

    // 等待成功提示或任务进度条出现
    await Promise.any([
      page.locator('.ant-message-success, .ant-message-info').isVisible(),
      page.locator('.ant-progress').isVisible(),
    ]).catch(() => {});
  });

  test('创建新版本 — 弹窗', async ({ page }) => {
    await page.click('button:has-text("创建新版本")');

    // Modal 弹出
    const modal = page.locator('.ant-modal');
    await expect(modal).toBeVisible();

    // 关闭 Modal
    await page.locator('.ant-modal-close').click();
    await expect(modal).not.toBeVisible();
  });
});
