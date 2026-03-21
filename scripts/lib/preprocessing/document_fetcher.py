#!/usr/bin/env python3
import os
import re
import subprocess
from contextlib import contextmanager
from typing import Generator
from lib.preprocessing.exceptions import DocumentFetchError


@contextmanager
def _change_directory(path: str) -> Generator[None, None, None]:
    """安全切换工作目录的 context manager"""
    old_cwd = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old_cwd)


FEISHU_URL_PATTERN = re.compile(r'/docx[/-]?([a-zA-Z0-9_-]{8,64})(?:\?[^/]*)?$')

DOC_TOKEN_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{8,64}$')

ALLOWED_DOMAINS = {
    'feishu.cn',
    'feishu.com',
    'bytedance.com',
    'larksuite.com'
}

SAFE_URL_TEMPLATE = 'https://feishu.cn/docx/{token}'


def _validate_feishu_url(document_url: str) -> str:
    """验证并提取飞书文档 URL 中的 token"""
    if not document_url or not isinstance(document_url, str):
        raise DocumentFetchError(f"无效的 URL: 必须是非空字符串")

    if len(document_url) > 2000:
        raise DocumentFetchError(f"URL 过长: {len(document_url)} > 2000")

    domain_match = re.search(r'^https?://([^/]+)', document_url)
    if not domain_match:
        raise DocumentFetchError(f"无效的 URL 格式: 缺少域名")

    domain = domain_match.group(1).split(':')[0].lower()

    if not any(domain.endswith(d) or d + '.' in domain for d in ALLOWED_DOMAINS):
        raise DocumentFetchError(
            f"不允许的域名: {domain}. "
            f"允许的域名: {', '.join(ALLOWED_DOMAINS)}"
        )

    url_match = FEISHU_URL_PATTERN.search(document_url)
    if not url_match:
        raise DocumentFetchError(
            f"无效的飞书 URL 格式: {document_url}. "
            f"期望格式: https://xxx.feishu.cn/.../docx/{{token}}"
        )

    doc_token = url_match.group(1)

    if not DOC_TOKEN_PATTERN.match(doc_token):
        raise DocumentFetchError(f"无效的文档 token 格式: {doc_token}")

    return doc_token


def fetch_feishu_document(
    document_url: str,
    output_dir: str = "/tmp",
    timeout: int = 30
) -> str:
    """获取飞书文档内容"""
    doc_token = _validate_feishu_url(document_url)
    safe_url = SAFE_URL_TEMPLATE.format(token=doc_token)
    md_filename = f"{doc_token}.md"

    try:
        os.makedirs(output_dir, exist_ok=True)

        with _change_directory(output_dir):
            result = subprocess.run(
                ['feishu2md', 'download', safe_url],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "未知错误"
                raise subprocess.CalledProcessError(
                    result.returncode,
                    ['feishu2md', 'download', safe_url],
                    result.stderr,
                    result.stdout
                )

            md_file_path = os.path.join(output_dir, md_filename)

            try:
                file_size = os.path.getsize(md_file_path)
            except OSError:
                raise DocumentFetchError(f"未生成 Markdown 文件: {md_file_path}")

            if file_size == 0:
                raise DocumentFetchError(f"生成的文件为空: {md_file_path}")

            if file_size > 10 * 1024 * 1024:
                raise DocumentFetchError(f"文件过大: {file_size} bytes")

            with open(md_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if not content.strip():
                raise DocumentFetchError(f"文件内容为空: {md_file_path}")

            return content

    except subprocess.CalledProcessError as e:
        error_msg = f"feishu2md 下载失败 (退出码: {e.returncode})"
        if e.stderr:
            error_msg += f"\n错误输出: {e.stderr}"
        raise DocumentFetchError(error_msg) from e

    except subprocess.TimeoutExpired:
        raise DocumentFetchError(f"下载超时 ({timeout}秒)")

    except FileNotFoundError:
        raise DocumentFetchError("feishu2md 未安装。请安装: gem install feishu2md")

    except PermissionError as e:
        raise DocumentFetchError(f"权限错误: {e}")

    except OSError as e:
        raise DocumentFetchError(f"系统错误: {e}")
