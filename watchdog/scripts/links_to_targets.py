from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import yaml


def read_links(path: Path) -> List[str]:
    if not path.exists():
        raise SystemExit(f"links file not found: {path}")

    lines = path.read_text(encoding="utf-8").splitlines()
    urls: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        urls.append(stripped)
    if not urls:
        raise SystemExit(f"no URLs found in {path} (file is empty or only comments)")
    return urls


def build_targets(urls: List[str]) -> dict:
    """
    Build a minimal WatchDog targets YAML structure from a list of URLs.
    """
    targets: List[dict] = []
    for idx, url in enumerate(urls, start=1):
        targets.append(
            {
                "name": f"Custom {idx}",
                "url": url,
                "expected_status": 200,
                "timeout": 8,
                "method": "GET",
                "latency_threshold_ms": 5000,
            }
        )
    return {"targets": targets}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a plain links.txt file (one URL per line) "
            "into a WatchDog targets YAML file."
        )
    )
    parser.add_argument(
        "--links-file",
        type=str,
        default="links.txt",
        help="Path to the input text file containing URLs (default: links.txt).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="config/targets_links.yaml",
        help="Path to the output targets YAML file (default: config/targets_links.yaml).",
    )
    args = parser.parse_args()

    links_path = Path(args.links_file)
    output_path = Path(args.output)

    urls = read_links(links_path)
    data = build_targets(urls)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    print(f"Wrote {len(urls)} targets to {output_path}")
    print()
    print("To run the monitor only for these links, use:")
    print(
        "  WATCHDOG_TARGETS_FILE="
        f"{output_path.as_posix()} python main.py --monitor"
    )


if __name__ == "__main__":
    main()

