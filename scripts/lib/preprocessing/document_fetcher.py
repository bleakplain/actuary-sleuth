#!/usr/bin/env python3
import os
import re
import subprocess
from lib.preprocessing.exceptions import DocumentFetchError


def fetch_feishu_document(document_url: str) -> str:
    match = re.search(r'/docx/([a-zA-Z0-9]+)', document_url)
    if not match:
        raise DocumentFetchError(f"Invalid Feishu document URL: {document_url}")

    doc_token = match.group(1)
    md_filename = f"{doc_token}.md"
    output_dir = "/tmp"

    try:
        os.makedirs(output_dir, exist_ok=True)
        old_cwd = os.getcwd()
        os.chdir(output_dir)

        result = subprocess.run(
            ['feishu2md', 'download', document_url],
            capture_output=True,
            text=True,
            timeout=30,
            check=True
        )

        os.chdir(old_cwd)
        md_file = os.path.join(output_dir, md_filename)

        if not os.path.exists(md_file):
            raise DocumentFetchError(f"Markdown file not generated: {md_file}")

        with open(md_file, 'r', encoding='utf-8') as f:
            return f.read()

    except subprocess.CalledProcessError as e:
        os.chdir(old_cwd)
        raise DocumentFetchError(f"feishu2md download failed: {e.stderr}")
    except subprocess.TimeoutExpired:
        os.chdir(old_cwd)
        raise DocumentFetchError("Timeout downloading document")
    except FileNotFoundError:
        os.chdir(old_cwd)
        raise DocumentFetchError("feishu2md not found. Install: gem install feishu2md")
