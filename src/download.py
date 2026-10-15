"""Download London Borough of Hounslow 'Invoices over £500' files (Open Government Licence).

Resource list comes from the data.gov.uk CKAN API; each resource page embeds a direct
blob URL which we extract and download into data/raw/.

    python src/download.py            # last 14 monthly files
    python src/download.py --all      # every file published
"""
import argparse
import re
import sys
import urllib.parse
from pathlib import Path

import requests

PACKAGE_API = "https://ckan.publishing.service.gov.uk/api/3/action/package_show?id=council-spending-over-f5001"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
BLOB_RE = re.compile(r"https://blob\.datopian\.com/resources/[^\"'\ ]+")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="download every resource, not just the latest 14")
    ap.add_argument("--last", type=int, default=14)
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    pkg = requests.get(PACKAGE_API, timeout=60).json()["result"]
    print(f"{pkg['title']} | {pkg['organization']['title']} | {pkg['license_title']}")
    resources = pkg["resources"] if args.all else pkg["resources"][-args.last:]

    for r in resources:
        page = requests.get(r["url"], timeout=60).text
        m = BLOB_RE.search(page)
        if not m:
            print(f"  ! no download link for {r['name']}", file=sys.stderr)
            continue
        url = m.group(0)
        fname = urllib.parse.unquote(url.rsplit("/", 1)[1])
        dest = RAW_DIR / fname
        if dest.exists():
            print(f"  = {fname} (already downloaded)")
            continue
        dest.write_bytes(requests.get(url, timeout=120).content)
        print(f"  + {fname} ({dest.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
