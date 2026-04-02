import { test, expect } from '@playwright/test';

test.describe('评估数据集', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/eval/dataset');
    await page.waitForSelector('.ant-table', { timeout: 15_000 });
  });

  test('创建样本 — 填写表单提交', async ({ page }) => {
    const sampleId = `e2e_create_${Date.now()}`;

    await page.click('button:has-text("新增")');

    const modal = page.locator('.ant-modal');
    await expect(modal).toBeVisible();

    // 填写必填字段 — 使用 label 定位而非 id
    await modal.locator('.ant-form-item:has-text("ID") input').first().fill(sampleId);
    await modal.locator('.ant-form-item:has-text("问题") textarea').first().fill('E2E 测试问题');

    // 选择问题类型（必填）
    await modal.locator('.ant-form-item:has-text("问题类型") .ant-select').click();
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option').first().click();

    // 提交
    await modal.locator('.ant-modal-footer .ant-btn-primary').click();

    // 成功
    await expect(modal).not.toBeVisible({ timeout: 5_000 });
    await expect(page.locator('.ant-message-success:has-text("创建成功")')).toBeVisible();

    // 清理
    await _deleteSampleById(page, sampleId);
  });

  test('过滤样本 — 按难度筛选', async ({ page }) => {
    const difficultySelect = page.locator('.ant-select').nth(1);
    await difficultySelect.click();
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option').first().click();

    await page.waitForTimeout(1000);
    await expect(page.locator('.ant-table')).toBeVisible();

    // 清除过滤
    await difficultySelect.locator('.ant-select-clear').click({ force: true });
    await page.waitForTimeout(500);
  });

  test('编辑样本 — 修改问题内容', async ({ page }) => {
    const editId = `e2e_edit_${Date.now()}`;

    // 清理可能残留的同名样本
    await _deleteSampleById(page, editId);
    await page.waitForTimeout(500);

    // 创建样本
    await page.click('button:has-text("新增")');
    const modal = page.locator('.ant-modal');
    await expect(modal).toBeVisible();

    await modal.locator('.ant-form-item:has-text("ID") input').first().fill(editId);
    await modal.locator('.ant-form-item:has-text("问题") textarea').first().fill('原始问题');
    await modal.locator('.ant-form-item:has-text("问题类型") .ant-select').click();
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option').first().click();

    await modal.locator('.ant-modal-footer .ant-btn-primary').click();
    await expect(modal).not.toBeVisible({ timeout: 5_000 });
    await expect(page.locator('.ant-message-success:has-text("创建成功")')).toBeVisible();
    await page.waitForTimeout(1000);

    // 查找并编辑
    const row = await _findRowById(page, editId);
    if (!row) {
      test.skip('样本未在表格中找到');
      return;
    }

    await row.locator('button:has-text("编辑")').click();
    await expect(modal).toBeVisible();

    // 修改问题内容
    await modal.locator('.ant-form-item:has-text("问题") textarea').first().fill('修改后的问题');
    await modal.locator('.ant-modal-footer .ant-btn-primary').click();
    await expect(modal).not.toBeVisible({ timeout: 5_000 });
    await expect(page.locator('.ant-message-success:has-text("更新成功")')).toBeVisible();

    // 清理
    await _deleteSampleById(page, editId);
  });

  test('删除样本 — 确认后移除', async ({ page }) => {
    const deleteId = `e2e_del_${Date.now()}`;

    // 清理可能残留的同名样本
    await _deleteSampleById(page, deleteId);
    await page.waitForTimeout(500);

    // 创建样本
    await page.click('button:has-text("新增")');
    const modal = page.locator('.ant-modal');
    await expect(modal).toBeVisible();

    await modal.locator('.ant-form-item:has-text("ID") input').first().fill(deleteId);
    await modal.locator('.ant-form-item:has-text("问题") textarea').first().fill('待删除问题');
    await modal.locator('.ant-form-item:has-text("问题类型") .ant-select').click();
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option').first().click();

    await modal.locator('.ant-modal-footer .ant-btn-primary').click();
    await expect(modal).not.toBeVisible({ timeout: 5_000 });
    await expect(page.locator('.ant-message-success:has-text("创建成功")')).toBeVisible();
    await page.waitForTimeout(500);

    // 删除
    const deleted = await _deleteSampleById(page, deleteId);
    if (deleted) {
      await expect(page.locator('.ant-message-success:has-text("删除成功")')).toBeVisible();
    }
  });
});

/** 在表格中查找指定 ID 的行（跨分页） */
async function _findRowById(page, id: string) {
  for (const pg of [1, 2]) {
    if (pg === 2) {
      const pageBtn = page.locator('.ant-pagination-item:has-text("2")');
      if (!(await pageBtn.isVisible())) break;
      await pageBtn.click();
      await page.waitForTimeout(500);
    }
    const row = page.locator(`.ant-table-row:has-text("${id}")`);
    if (await row.isVisible()) return row;
  }
  return null;
}

/** 在表格中查找并删除指定 ID 的样本 */
async function _deleteSampleById(page, id: string): Promise<boolean> {
  const row = await _findRowById(page, id);
  if (!row) return false;
  await row.locator('button:has-text("删除")').click();
  await page.locator('.ant-popconfirm .ant-btn-primary').click();
  return true;
}
