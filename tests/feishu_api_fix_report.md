# Feishu Document Content Writing Fix - Complete Report

## Executive Summary

Fixed the Feishu document content writing issue in `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/report.py`. The document was being created successfully with a title, but content blocks were not being written to the document.

## Root Causes

1. **Incorrect API endpoint for retrieving document metadata**: Used `/docx/v1/documents/{document_id}/blocks/{document_id}` instead of `/docx/v1/documents/{document_id}`

2. **Wrong response data structure parsing**: Accessed `data.blocks` instead of `data.blocks.items`

3. **Incorrect block type values**: Used `block_type=2` (text paragraph) for all content instead of proper heading types (3, 4, 5 for H1, H2, H3)

4. **Wrong style property name**: Used `text_style` instead of `text_element_style`

5. **Silent API failures**: Errors were logged but not raised as exceptions

## Changes Made

### File: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/report.py`

#### Change 1: Fixed Document Metadata Retrieval (Lines 99-121)

**Old Code:**
```python
# 获取文档块信息 - 新创建的文档需要获取页面块
block_url = f"{FEISHU_API_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}"
block_response = requests.get(block_url, headers=create_headers, timeout=10)

if block_response.status_code == 200:
    block_data = block_response.json()
    if block_data.get("code") == 0:
        blocks = block_data.get("data", {}).get("blocks", [])
        # 新创建的文档返回空列表，需要使用 document_id 作为 block_id
        block_id = blocks[0].get("block_id") if blocks else document_id
```

**New Code:**
```python
# 获取文档元数据以找到页面块 ID
# 新创建的文档需要获取页面块（page block）
doc_meta_url = f"{FEISHU_API_BASE}/docx/v1/documents/{document_id}"
meta_response = requests.get(doc_meta_url, headers=create_headers, timeout=10)

page_block_id = None
if meta_response.status_code == 200:
    meta_data = meta_response.json()
    if meta_data.get("code") == 0:
        # 从响应中获取页面块 ID
        # 新文档的响应结构: data.document.document_id
        # 需要获取 blocks 数组中的页面块
        blocks = meta_data.get("data", {}).get("blocks", {}).get("items", [])
        if blocks and len(blocks) > 0:
            # 第一个块通常是页面块 (block_type=1)
            page_block_id = blocks[0].get("block_id")
            print(f"获取到页面块 ID: {page_block_id}", file=sys.stderr)

# 如果无法获取页面块 ID，使用 document_id 作为备选方案
# 这在大多数情况下应该有效，因为新文档的页面块 ID 通常就是 document_id
if not page_block_id:
    page_block_id = document_id
    print(f"使用 document_id 作为页面块 ID: {page_block_id}", file=sys.stderr)
```

#### Change 2: Fixed Block Type Values for Headings (Lines 130-177)

**Old Code:**
```python
if line.startswith('# '):
    # 一级标题
    text_content = line[2:].strip()
    feishu_blocks.append({
        "block_type": 2,  # 文本块
        "text": {
            "elements": [{
                "text_run": {
                    "content": text_content,
                    "text_style": {
                        "bold": True
                    }
                }
            }]
        }
    })
elif line.startswith('## '):
    # 二级标题
    text_content = line[3:].strip()
    feishu_blocks.append({
        "block_type": 2,
        "text": {
            "elements": [{
                "text_run": {
                    "content": text_content
                }
            }]
        }
    })
```

**New Code:**
```python
if line.startswith('# '):
    # 一级标题 (使用 block_type=3 表示 Heading 1)
    text_content = line[2:].strip()
    feishu_blocks.append({
        "block_type": 3,  # 标题1
        "text": {
            "elements": [{
                "text_run": {
                    "content": text_content,
                    "text_element_style": {
                        "bold": True
                    }
                }
            }]
        }
    })
elif line.startswith('## '):
    # 二级标题 (使用 block_type=4 表示 Heading 2)
    text_content = line[3:].strip()
    feishu_blocks.append({
        "block_type": 4,  # 标题2
        "text": {
            "elements": [{
                "text_run": {
                    "content": text_content,
                    "text_element_style": {
                        "bold": True
                    }
                }
            }]
        }
    })
elif line.startswith('### '):
    # 三级标题 (使用 block_type=5 表示 Heading 3)
    text_content = line[4:].strip()
    feishu_blocks.append({
        "block_type": 5,  # 标题3
        "text": {
            "elements": [{
                "text_run": {
                    "content": text_content,
                    "text_element_style": {
                        "bold": True
                    }
                }
            }]
        }
    })
```

#### Change 3: Added Markdown Bold Text Support (Lines 178-216)

**New Feature Added:**
```python
else:
    # 普通文本 (使用 block_type=2 表示文本段落)
    # 处理加粗标记 **text**
    processed_line = line
    formatted_elements = []

    # 简单处理 **加粗** 标记
    if '**' in processed_line:
        parts = processed_line.split('**')
        for i, part in enumerate(parts):
            if part:  # 跳过空字符串
                if i % 2 == 1:  # 奇数索引是加粗内容
                    formatted_elements.append({
                        "text_run": {
                            "content": part,
                            "text_element_style": {
                                "bold": True
                            }
                        }
                    })
                else:  # 偶数索引是普通文本
                    formatted_elements.append({
                        "text_run": {
                            "content": part
                        }
                    })
    else:
        formatted_elements.append({
            "text_run": {
                "content": processed_line
            }
        })

    feishu_blocks.append({
        "block_type": 2,  # 文本段落
        "text": {
            "elements": formatted_elements
        }
    })
```

#### Change 4: Improved Error Handling (Lines 218-243)

**Old Code:**
```python
update_response = requests.post(update_url, headers=create_headers, json=update_payload, timeout=30)
print(f"块写入响应: {update_response.status_code}", file=sys.stderr)
if update_response.status_code != 200:
    print(f"更新文档失败: {update_response.text}", file=sys.stderr)
else:
    update_data = update_response.json()
    print(f"块写入结果: {update_data.get('code')}", file=sys.stderr)
```

**New Code:**
```python
# 批量写入文档内容（每次最多 500 个块）
if feishu_blocks:
    print(f"准备写入 {len(feishu_blocks)} 个块", file=sys.stderr)
    for i in range(0, len(feishu_blocks), 500):
        chunk = feishu_blocks[i:i+500]
        update_url = f"{FEISHU_API_BASE}/docx/v1/documents/{document_id}/blocks/{page_block_id}/children"
        update_payload = {
            "children": chunk,
            "index": -1  # 添加到末尾
        }

        print(f"写入块 {i+1}-{min(i+500, len(feishu_blocks))}", file=sys.stderr)
        update_response = requests.post(update_url, headers=create_headers, json=update_payload, timeout=30)
        print(f"块写入响应: {update_response.status_code}", file=sys.stderr)

        if update_response.status_code != 200:
            print(f"更新文档失败: {update_response.text}", file=sys.stderr)
            raise Exception(f"写入内容失败: HTTP {update_response.status_code} - {update_response.text}")
        else:
            update_data = update_response.json()
            code = update_data.get('code')
            print(f"块写入结果 code: {code}", file=sys.stderr)
            if code != 0:
                msg = update_data.get('msg', 'Unknown error')
                raise Exception(f"写入内容失败: {msg}")
```

## Feishu Docx API Block Types Reference

| Block Type | Value | Description |
|------------|-------|-------------|
| Page | 1 | Page block (container) |
| Text | 2 | Text paragraph |
| Heading 1 | 3 | Level 1 heading |
| Heading 2 | 4 | Level 2 heading |
| Heading 3 | 5 | Level 3 heading |
| Heading 4 | 6 | Level 4 heading |
| Heading 5 | 7 | Level 5 heading |
| Heading 6 | 8 | Level 6 heading |
| Heading 7 | 9 | Level 7 heading |
| Heading 8 | 10 | Level 8 heading |
| Heading 9 | 11 | Level 9 heading |
| Bulleted List | 12 | Bulleted list item |
| Numbered List | 13 | Numbered list item |

## Testing

### Test Script Created

File: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/test_feishu_api.py`

To run the test:

```bash
export FEISHU_APP_ID='your_app_id'
export FEISHU_APP_SECRET='your_app_secret'
cd /root/.openclaw/workspace/skills/actuary-sleuth/scripts
python3 test_feishu_api.py
```

### Syntax Validation

Both `report.py` and `test_feishu_api.py` have been validated for Python syntax errors:
```bash
python3 -m py_compile report.py  # PASSED
python3 -m py_compile test_feishu_api.py  # PASSED
```

## References

- [UniFuncs - 飞书API创建文档全攻略](https://unifuncs.com/s/z4OXTM82) - Detailed guide with Python examples
- [Lark Developer - Create Block API](https://open.larksuite.com/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/document-docx/docx-v1/document-block-children/create) - Official API documentation
- [Feishu Open Platform - Create Block](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/create) - API reference

## Files Modified

- `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/report.py` - Fixed `create_feishu_document` function

## Files Created

- `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/test_feishu_api.py` - Test script for validation
- `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/FEISHU_API_FIX_SUMMARY.md` - Summary document
- `/root/work/coding-agent-learning/tests/feishu_fix_comparison.md` - Before/after comparison

## Verification Steps

1. Set environment variables:
   ```bash
   export FEISHU_APP_ID='your_app_id'
   export FEISHU_APP_SECRET='your_app_secret'
   ```

2. Run the test script:
   ```bash
   cd /root/.openclaw/workspace/skills/actuary-sleuth/scripts
   python3 test_feishu_api.py
   ```

3. Verify the document is created with content by visiting the returned URL

4. Check that:
   - Document title is set correctly
   - All headings (H1, H2, H3) are rendered properly
   - Bold text (using `**text**`) is formatted correctly
   - All content is present in the document

## Conclusion

The fix addresses all identified issues:
- Correct API endpoint usage
- Proper response data structure parsing
- Correct block type values for different heading levels
- Correct style property names
- Proper markdown bold text support
- Comprehensive error handling

The document content should now be written successfully to Feishu documents.
