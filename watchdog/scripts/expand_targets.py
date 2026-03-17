from __future__ import annotations

"""
Utility script to synthetically expand a targets YAML file
to a larger number of entries (e.g. 800–1000) for load testing.

Usage (from project root):

  cd ~/software/WEB-MONITOR
  source .venv/bin/activate

  python watchdog/scripts/expand_targets.py \
    --input  watchdog/config/targets_public_institutions.yaml \
    --output watchdog/config/targets_public_institutions_expanded.yaml \
    --target-count 900

Then point WATCHDOG_TARGETS_FILE to the expanded file:
  - In .env (local)    : WATCHDOG_TARGETS_FILE=watchdog/config/targets_public_institutions_expanded.yaml
  - In docker-compose  : WATCHDOG_TARGETS_FILE: /app/config/targets_public_institutions_expanded.yaml
"""

import argparse
from pathlib import Path
from typing import Any, List

import yaml


def _load_targets(path: Path) -> List[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "targets" not in data:
        raise SystemExit(f"Input file {path} does not have a top-level 'targets' list.")
    targets = data["targets"]
    if not isinstance(targets, list):
        raise SystemExit(f"'targets' in {path} is not a list.")
    if not targets:
        raise SystemExit(f"No targets found in {path}.")
    return targets


def _write_targets(path: Path, targets: List[dict[str, Any]]) -> None:
    payload = {"targets": targets}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def expand_targets(input_path: Path, output_path: Path, target_count: int) -> None:
    base_targets = _load_targets(input_path)
    original_count = len(base_targets)

    if target_count <= original_count:
        # Just copy as-is.
        _write_targets(output_path, base_targets)
        print(
            f"Requested target_count ({target_count}) <= original_count ({original_count}); "
            f"copied input to {output_path} without expansion."
        )
        return

    expanded: List[dict[str, Any]] = []
    idx = 0
    while len(expanded) < target_count:
        base = base_targets[idx % original_count]
        clone = dict(base)  # shallow copy is fine (values are scalars)

        # Make URL unique by appending a synthetic query parameter.
        url = str(clone.get("url"))
        suffix = len(expanded) + 1
        if "?" in url:
            new_url = f"{url}&shard={suffix}"
        else:
            new_url = f"{url}?shard={suffix}"
        clone["url"] = new_url

        expanded.append(clone)
        idx += 1

    _write_targets(output_path, expanded)
    print(
        f"Expanded {original_count} base targets to {len(expanded)} targets "
        f"into {output_path}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Expand a targets YAML file for load testing.")
    parser.add_argument("--input", type=Path, required=True, help="Input targets YAML path.")
    parser.add_argument("--output", type=Path, required=True, help="Output expanded YAML path.")
    parser.add_argument(
        "--target-count",
        type=int,
        required=True,
        help="Desired number of targets in the expanded file (e.g. 800 or 1000).",
    )
    args = parser.parse_args()

    expand_targets(args.input, args.output, args.target_count)


if __name__ == "__main__":
    main()

