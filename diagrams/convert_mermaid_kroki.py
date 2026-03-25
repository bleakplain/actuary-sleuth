#!/usr/bin/env python3
"""
Convert Mermaid diagrams to PNG using Kroki.io rendering service
"""
import os
import requests
import zlib
import base64
import time
from pathlib import Path
from urllib.parse import quote

# Kroki.io API endpoint
KROKI_API = "https://kroki.io/mermaid/png/"

def convert_mermaid_to_png(mmd_file: str, output_file: str) -> bool:
    """Convert a Mermaid file to PNG using Kroki.io service"""

    # Read the Mermaid content
    with open(mmd_file, 'r', encoding='utf-8') as f:
        mermaid_code = f.read()

    try:
        # Encode the diagram using deflate compression and base64
        compressed = zlib.compress(mermaid_code.encode('utf-8'), level=9)
        encoded = base64.urlsafe_b64encode(compressed).decode('ascii')

        # Build the URL
        url = f"{KROKI_API}{encoded}"

        # Fetch the rendered PNG
        response = requests.get(url, timeout=30)

        if response.status_code == 200:
            # Save the PNG
            with open(output_file, 'wb') as f:
                f.write(response.content)
            print(f"✅ Converted: {Path(mmd_file).name} → {Path(output_file).name}")
            return True
        else:
            print(f"❌ Failed to convert {Path(mmd_file).name}: HTTP {response.status_code}")
            return False

    except Exception as e:
        print(f"❌ Error converting {Path(mmd_file).name}: {e}")
        return False

def main():
    """Convert all Mermaid files in the diagrams directory"""

    diagrams_dir = Path("/root/.openclaw/workspace/skills/actuary-sleuth/diagrams")
    mmd_files = sorted(diagrams_dir.glob("*.mmd"))

    print(f"Found {len(mmd_files)} Mermaid diagrams to convert...")
    print("=" * 60)

    success_count = 0
    for mmd_file in mmd_files:
        output_file = mmd_file.with_suffix('.png')

        if convert_mermaid_to_png(str(mmd_file), str(output_file)):
            success_count += 1

        # Rate limiting - be nice to the API
        time.sleep(0.5)

    print("=" * 60)
    print(f"\n✅ Successfully converted {success_count}/{len(mmd_files)} diagrams")

    # List converted files
    if success_count > 0:
        print("\n📁 Converted files:")
        for png_file in sorted(diagrams_dir.glob("*.png")):
            size = png_file.stat().st_size
            print(f"   - {png_file.name} ({size:,} bytes)")

if __name__ == "__main__":
    main()
