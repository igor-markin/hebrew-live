#!/usr/bin/env python3
"""Sample one macOS process tree without treating unified memory as additive GPU RAM."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time


SWAP = re.compile(r"used = ([0-9.]+)([KMG])")
FREE = re.compile(r"System-wide memory free percentage:\s*(\d+)%")
SCALE = {"K": 1024, "M": 1024**2, "G": 1024**3}


def command(*parts: str) -> str:
    result = subprocess.run(parts, check=False, capture_output=True, text=True)
    return result.stdout.strip()


def process_rows() -> dict[int, tuple[int, int, str]]:
    rows: dict[int, tuple[int, int, str]] = {}
    for line in command("/bin/ps", "-axo", "pid=,ppid=,rss=,command=").splitlines():
        fields = line.strip().split(None, 3)
        if len(fields) != 4:
            continue
        try:
            pid, parent, rss = map(int, fields[:3])
        except ValueError:
            continue
        rows[pid] = (parent, rss * 1024, fields[3])
    return rows


def process_tree(root: int, rows: dict[int, tuple[int, int, str]]) -> set[int]:
    found = {root}
    changed = True
    while changed:
        changed = False
        for pid, (parent, _rss, _command) in rows.items():
            if parent in found and pid not in found:
                found.add(pid)
                changed = True
    return found


def swap_used_bytes() -> int | None:
    match = SWAP.search(command("/usr/sbin/sysctl", "-n", "vm.swapusage"))
    return round(float(match[1]) * SCALE[match[2]]) if match else None


def memory_free_percent() -> int | None:
    match = FREE.search(command("/usr/bin/memory_pressure", "-Q"))
    return int(match[1]) if match else None


def write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def optional_extreme(values: list[int | None], *, largest: bool) -> int | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return max(present) if largest else min(present)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-pid", type=int, required=True)
    parser.add_argument("--duration-seconds", type=float, default=1800)
    parser.add_argument("--interval-seconds", type=float, default=10)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    started = time.monotonic()
    report: dict[str, object] = {
        "schema_version": 1,
        "root_pid": options.root_pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "samples": [],
        "note": "Process RSS and MLX peak memory share Apple unified memory and must not be added.",
    }
    samples: list[dict[str, object]] = report["samples"]  # type: ignore[assignment]
    while True:
        rows = process_rows()
        if options.root_pid not in rows:
            report["process_exited"] = True
            break
        pids = process_tree(options.root_pid, rows)
        sample = {
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "process_count": len(pids),
            "process_rss_bytes": sum(rows[pid][1] for pid in pids if pid in rows),
            "largest_process_rss_bytes": max((rows[pid][1] for pid in pids if pid in rows), default=0),
            "memory_free_percent": memory_free_percent(),
            "swap_used_bytes": swap_used_bytes(),
        }
        samples.append(sample)
        report["summary"] = {
            "sample_count": len(samples),
            "measured_seconds": sample["elapsed_seconds"],
            "peak_process_rss_bytes": max(item["process_rss_bytes"] for item in samples),
            "peak_largest_process_rss_bytes": max(item["largest_process_rss_bytes"] for item in samples),
            "minimum_memory_free_percent": optional_extreme(
                [item["memory_free_percent"] for item in samples], largest=False
            ),
            "peak_swap_used_bytes": optional_extreme(
                [item["swap_used_bytes"] for item in samples], largest=True
            ),
        }
        write_report(options.output, report)
        if sample["elapsed_seconds"] >= options.duration_seconds:
            break
        time.sleep(min(options.interval_seconds, max(0, options.duration_seconds - float(sample["elapsed_seconds"]))))
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_report(options.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
