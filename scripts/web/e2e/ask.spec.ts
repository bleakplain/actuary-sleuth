import { test, expect } from '@playwright/test';

/**
 * 法规问答页面 E2E 测试
 *
 * 部分测试需要 RAG 引擎就绪（通过实际搜索请求验证），
 * 不满足条件时自动 skip。
 */

async function isRagReady(request): Promise<boolean> {
  try {
    const resp = await request.post('http://localhost:8000/api/ask/chat', {
      data: { question: '测试', mode: 'search' },
    });
    return resp.ok() && resp.status() === 200;
  } catch {
    return false;
  }
}

/** 清除所有已有对话，确保测试隔离 */
async function cleanAllConversations(page) {
  // 刷新页面以加载最新对话列表
  await page.reload();
  await page.waitForSelector('text=对话历史', { timeout: 10_000 });
  await page.waitForTimeout(1000);

  // 逐个删除
  for (let attempt = 0; attempt < 50; attempt++) {
    const items = page.locator('.conversation-item');
    const count = await items.count();
    if (count === 0) return;

    // 点击最后一个对话的删除按钮
    await items.last().locator('button.ant-btn-text').click();
    await page.locator('.ant-popconfirm').waitFor({ state: 'visible', timeout: 5_000 });
    await page.locator('.ant-popconfirm .ant-btn-primary').click();
    await page.waitForTimeout(1000);
  }
}

test.describe('法规问答 — 页面与 UI', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/ask');
    await page.waitForSelector('text=输入问题，检索保险法规并获取带引用的回答', { timeout: 10_000 });
  });

  test('页面初始状态 — 空对话列表、输入框、模式切换', async ({ page }) => {
    await expect(page.locator('text=对话历史')).toBeVisible();
    await expect(page.getByPlaceholder('输入法规相关问题...')).toBeVisible();
    await expect(page.getByRole('button', { name: /send/ })).toBeDisabled();

    const radios = page.locator('.ant-radio-button-wrapper');
    await expect(radios.first()).toHaveClass(/ant-radio-button-wrapper-checked/);
    await expect(radios.nth(1)).not.toHaveClass(/ant-radio-button-wrapper-checked/);

    await expect(page.locator('text=输入问题，检索保险法规并获取带引用的回答')).toBeVisible();
  });

  test('输入框交互 — 输入文字后发送按钮启用', async ({ page }) => {
    const sendBtn = page.getByRole('button', { name: /send/ });
    await expect(sendBtn).toBeDisabled();

    const input = page.getByPlaceholder('输入法规相关问题...');
    await input.click();
    await input.type('测试问题');

    await expect(sendBtn).toBeEnabled();
    await input.clear();
    await expect(sendBtn).toBeDisabled();
  });

  test('模式切换 — 智能问答 ↔ 精确检索', async ({ page }) => {
    const radios = page.locator('.ant-radio-button-wrapper');

    await expect(radios.first()).toHaveClass(/ant-radio-button-wrapper-checked/);

    await radios.nth(1).click();
    await expect(radios.nth(1)).toHaveClass(/ant-radio-button-wrapper-checked/);
    await expect(radios.first()).not.toHaveClass(/ant-radio-button-wrapper-checked/);

    await radios.first().click();
    await expect(radios.first()).toHaveClass(/ant-radio-button-wrapper-checked/);
    await expect(radios.nth(1)).not.toHaveClass(/ant-radio-button-wrapper-checked/);
  });

  test('搜索提问 — 用户消息和对话列表出现', async ({ page }) => {
    if (!(await isRagReady(page.request))) {
      test.skip('RAG 搜索不可用');
      return;
    }

    await cleanAllConversations(page);

    await page.locator('.ant-radio-button-wrapper').nth(1).click();
    const input = page.getByPlaceholder('输入法规相关问题...');
    await input.click();
    await input.type('健康保险等待期');
    await page.getByRole('button', { name: /send/ }).click();

    // 等待对话出现在侧边栏
    await page.locator('.conversation-item').first().waitFor({ state: 'visible', timeout: 30_000 });
    await expect(page.locator('.conversation-item')).toHaveCount(1);

    // 点击对话切换到该对话
    await page.locator('.conversation-item').first().click();
    await page.waitForTimeout(1000);
    await expect(page.locator('text=健康保险等待期').first()).toBeVisible();
  });

  test('对话管理 — 删除对话后列表清空', async ({ page }) => {
    if (!(await isRagReady(page.request))) {
      test.skip('RAG 搜索不可用');
      return;
    }

    await cleanAllConversations(page);

    await page.locator('.ant-radio-button-wrapper').nth(1).click();
    const input = page.getByPlaceholder('输入法规相关问题...');
    await input.click();
    await input.type('保险费率规定');
    await page.getByRole('button', { name: /send/ }).click();
    await page.locator('.conversation-item').first().waitFor({ state: 'visible', timeout: 30_000 });
    await page.waitForTimeout(1000);

    await expect(page.locator('.conversation-item')).toHaveCount(1);

    await page.locator('.conversation-item').first().locator('button.ant-btn-text').click();
    await page.locator('.ant-popconfirm').waitFor({ state: 'visible', timeout: 5_000 });
    await page.locator('.ant-popconfirm .ant-btn-primary').click();

    await page.waitForTimeout(1000);
    await expect(page.locator('.conversation-item')).toHaveCount(0, { timeout: 5_000 });
  });

  test('多轮对话 — 切换对话加载不同消息', async ({ page }) => {
    if (!(await isRagReady(page.request))) {
      test.skip('RAG 搜索不可用');
      return;
    }

    await cleanAllConversations(page);

    await page.locator('.ant-radio-button-wrapper').nth(1).click();
    const input = page.getByPlaceholder('输入法规相关问题...');
    await input.click();
    await input.type('第一个问题');
    await page.getByRole('button', { name: /send/ }).click();
    await page.locator('.conversation-item').first().waitFor({ state: 'visible', timeout: 30_000 });
    await page.waitForTimeout(1000);

    await page.getByPlaceholder('输入法规相关问题...').click();
    await page.getByPlaceholder('输入法规相关问题...').type('第二个问题');
    await page.getByRole('button', { name: /send/ }).click();
    await page.waitForTimeout(3000);

    await expect(page.locator('.conversation-item')).toHaveCount(2);

    await page.locator('.conversation-item').first().click();
    await page.waitForTimeout(1000);
    await expect(page.locator('text=第一个问题')).toBeVisible();

    await page.locator('.conversation-item').nth(1).click();
    await page.waitForTimeout(1000);
    await expect(page.locator('text=第二个问题')).toBeVisible();
  });

  test('对话管理 — 取消删除不删除', async ({ page }) => {
    if (!(await isRagReady(page.request))) {
      test.skip('RAG 搜索不可用');
      return;
    }

    await cleanAllConversations(page);

    await page.locator('.ant-radio-button-wrapper').nth(1).click();
    const input = page.getByPlaceholder('输入法规相关问题...');
    await input.click();
    await input.type('取消删除测试');
    await page.getByRole('button', { name: /send/ }).click();
    await page.locator('.conversation-item').first().waitFor({ state: 'visible', timeout: 30_000 });
    await page.waitForTimeout(1000);

    await expect(page.locator('.conversation-item')).toHaveCount(1);

    await page.locator('.conversation-item').first().locator('button.ant-btn-text').click();
    await expect(page.locator('.ant-popconfirm')).toBeVisible();
    await page.locator('.ant-popconfirm .ant-btn-default').click();

    await expect(page.locator('.conversation-item')).toHaveCount(1);

    // 清理
    await page.locator('.conversation-item').first().locator('button.ant-btn-text').click();
    await page.locator('.ant-popconfirm .ant-btn-primary').click();
    await page.waitForTimeout(1000);
  });
});
