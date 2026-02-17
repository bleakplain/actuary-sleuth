# Before/After Comparison - Feishu API Fix

## Function: `create_feishu_document`

### Issue 1: Block Retrieval Endpoint

**BEFORE (Incorrect):**
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

**AFTER (Correct):**
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
if not page_block_id:
    page_block_id = document_id
    print(f"使用 document_id 作为页面块 ID: {page_block_id}", file=sys.stderr)
```

**Key Changes:**
- Changed endpoint from `/documents/{id}/blocks/{id}` to `/documents/{id}`
- Changed response parsing from `data.blocks` to `data.blocks.items`
- Added fallback logic using `document_id` if page block not found

---

### Issue 2: Block Type Values

**BEFORE (Incorrect):**
```python
if line.startswith('# '):
    # 一级标题
    text_content = line[2:].strip()
    feishu_blocks.append({
        "block_type": 2,  # 文本块 (WRONG!)
        "text": {
            "elements": [{
                "text_run": {
                    "content": text_content,
                    "text_style": {  # Wrong property name
                        "bold": True
                    }
                }
            }]
        }
    })
```

**AFTER (Correct):**
```python
if line.startswith('# '):
    # 一级标题 (使用 block_type=3 表示 Heading 1)
    text_content = line[2:].strip()
    feishu_blocks.append({
        "block_type": 3,  # 标题1 (CORRECT!)
        "text": {
            "elements": [{
                "text_run": {
                    "content": text_content,
                    "text_element_style": {  # Correct property name
                        "bold": True
                    }
                }
            }]
        }
    })
```

**Key Changes:**
- Changed `block_type` from 2 (text) to 3 (heading 1)
- Changed property name from `text_style` to `text_element_style`

---

### Issue 3: Missing Heading Level 3 Support

**BEFORE:**
```python
# Only handled # and ## headings
if line.startswith('# '):
    # Level 1
elif line.startswith('## '):
    # Level 2
else:
    # Regular text
```

**AFTER:**
```python
# Now handles #, ##, and ### headings
if line.startswith('# '):
    # Level 1 - block_type=3
elif line.startswith('## '):
    # Level 2 - block_type=4
elif line.startswith('### '):
    # Level 3 - block_type=5 (NEW!)
else:
    # Regular text - block_type=2
```

---

### Issue 4: Markdown Bold Text Support

**BEFORE:**
```python
# No handling of **bold** markdown
feishu_blocks.append({
    "block_type": 2,
    "text": {
        "elements": [{
            "text_run": {
                "content": line  # Entire line as plain text
            }
        }]
    }
})
```

**AFTER:**
```python
# Handles **bold** markdown syntax
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

---

### Issue 5: Error Handling

**BEFORE (Silent Failures):**
```python
update_response = requests.post(update_url, headers=create_headers, json=update_payload, timeout=30)
print(f"块写入响应: {update_response.status_code}", file=sys.stderr)
if update_response.status_code != 200:
    print(f"更新文档失败: {update_response.text}", file=sys.stderr)
else:
    update_data = update_response.json()
    print(f"块写入结果: {update_data.get('code')}", file=sys.stderr)
# Code continues even on failure
```

**AFTER (Proper Error Handling):**
```python
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

---

## Summary of All Changes

| Aspect | Before | After |
|--------|--------|-------|
| Document metadata endpoint | `/documents/{id}/blocks/{id}` | `/documents/{id}` |
| Block data path | `data.blocks` | `data.blocks.items` |
| Page block ID fallback | Used document_id directly | Gets from metadata first, falls back to document_id |
| Heading 1 block_type | 2 (text) | 3 (heading 1) |
| Heading 2 block_type | 2 (text) | 4 (heading 2) |
| Heading 3 support | None | 5 (heading 3) |
| Style property name | `text_style` | `text_element_style` |
| Markdown bold support | None | Full support |
| Error handling | Logged only | Raises exceptions |
| Debug output | Minimal | Comprehensive |

---

## API Endpoints Used

1. **Create Document:**
   - Method: `POST`
   - URL: `/docx/v1/documents`
   - Body: `{"title": "...", "folder_token": ""}`

2. **Get Document Metadata:**
   - Method: `GET`
   - URL: `/docx/v1/documents/{document_id}`
   - Returns: Document with blocks array containing page block

3. **Create Block Children:**
   - Method: `POST`
   - URL: `/docx/v1/documents/{document_id}/blocks/{block_id}/children`
   - Body: `{"children": [...], "index": -1}`
