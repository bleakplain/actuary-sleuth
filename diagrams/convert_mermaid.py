#!/usr/bin/env python3
"""
Convert Mermaid diagrams to PNG using online rendering service
"""
import os
import requests
import base64
import time
from pathlib import Path

# Mermaid Live Editor API endpoint
MERMAID_API = "https://mermaid.live/api/v1/render"

def convert_mermaid_to_png(mmd_file: str, output_file: str) -> bool:
    """Convert a Mermaid file to PNG using online service"""

    # Read the Mermaid content
    with open(mmd_file, 'r', encoding='utf-8') as f:
        mermaid_code = f.read()

    try:
        # Use Mermaid Live Editor API
        response = requests.post(
            MERMAID_API,
            json={
                "code": mermaid_code,
                "format": "png"
            },
            timeout=30
        )

        if response.status_code == 200:
            # Save the PNG
            with open(output_file, 'wb') as f:
                f.write(response.content)
            print(f"✅ Converted: {mmd_file} → {output_file}")
            return True
        else:
            print(f"❌ Failed to convert {mmd_file}: HTTP {response.status_code}")
            return False

    except Exception as e:
        print(f"❌ Error converting {mmd_file}: {e}")
        return False

def main():
    """Convert all Mermaid files in the diagrams directory"""

    diagrams_dir = Path("/root/.openclaw/workspace/skills/actuary-sleuth/diagrams")
    mmd_files = list(diagrams_dir.glob("*.mmd"))

    print(f"Found {len(mmd_files)} Mermaid diagrams to convert...")

    success_count = 0
    for mmd_file in mmd_files:
        output_file = mmd_file.with_suffix('.png')

        if convert_mermaid_to_png(str(mmd_file), str(output_file)):
            success_count += 1

        # Rate limiting - be nice to the API
        time.sleep(1)

    print(f"\n✅ Successfully converted {success_count}/{len(mmd_files)} diagrams")

if __name__ == "__main__":
    main()
