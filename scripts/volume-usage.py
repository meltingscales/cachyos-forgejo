#!/usr/bin/env python3
"""
volume-usage.py

Show disk usage of Docker Compose volumes.
Breaks down by top 10 largest directories within each volume.
"""

import json
import subprocess
import sys
from pathlib import Path


def get_volumes():
    """Get list of Docker Compose volumes."""
    # Get current project name from docker compose
    try:
        result = subprocess.run(
            ['docker', 'compose', 'ps', '--format', 'json'],
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Error getting Docker Compose info: {e}", file=sys.stderr)
        sys.exit(1)

    if not result.stdout.strip():
        print("No Docker Compose project found.", file=sys.stderr)
        sys.exit(1)

    # Get project name from compose output
    try:
        compose_data = json.loads(result.stdout)
        if not compose_data:
            print("No Docker Compose project found.", file=sys.stderr)
            sys.exit(1)

        project_name = compose_data[0].get('Project', '')
        if not project_name:
            print("Could not determine project name from compose data.", file=sys.stderr)
            sys.exit(1)
    except (json.JSONDecodeError, IndexError, KeyError):
        print("Could not determine project name.", file=sys.stderr)
        sys.exit(1)

    # Get all volumes and filter by project name
    volumes = {}
    try:
        result = subprocess.run(
            ['docker', 'volume', 'ls', '--format', '{{.Name}}'],
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError:
        return {}

    for vol_name in result.stdout.strip().split('\n'):
        if not vol_name:
            continue

        # Only include volumes from our project
        if project_name.lower() in vol_name.lower():
            try:
                inspect_result = subprocess.run(
                    ['docker', 'volume', 'inspect', vol_name],
                    capture_output=True,
                    text=True,
                    check=True
                )
                vol_data = json.loads(inspect_result.stdout)
                mountpoint = vol_data[0].get('Mountpoint', '')
                if mountpoint:
                    volumes[vol_name] = mountpoint
            except (subprocess.CalledProcessError, json.JSONDecodeError, IndexError):
                continue

    return volumes


def get_directory_size(path):
    """Get total size of a directory in bytes."""
    try:
        result = subprocess.run(
            ['du', '-sb', path],
            capture_output=True,
            text=True,
            check=True
        )
        return int(result.stdout.split()[0])
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return 0


def format_size(bytes_size):
    """Format bytes to human readable size."""
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PiB"


def get_top_directories(mountpoint, limit=10):
    """Get top N largest directories within a volume."""
    try:
        result = subprocess.run(
            ['du', '-h', '--max-depth=2', mountpoint],
            capture_output=True,
            text=True,
            check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    lines = result.stdout.strip().split('\n')
    # Parse and sort by size
    dirs = []
    for line in lines:
        parts = line.split('\t')
        if len(parts) >= 2:
            size_str = parts[0]
            path = parts[1] if len(parts) == 2 else '\t'.join(parts[1:])
            # Skip the root entry
            if path == mountpoint:
                continue
            dirs.append((size_str, path))

    # Sort by size (du already sorts, but let's be safe)
    # Just take the last entries since du sorts ascending
    return dirs[-limit:]


def main():
    volumes = get_volumes()

    if not volumes:
        print("No Docker Compose volumes found.")
        return

    print("Docker Compose Volume Usage")
    print("=" * 60)

    total_size = 0

    for vol_name, mountpoint in volumes.items():
        size = get_directory_size(mountpoint)
        total_size += size
        size_human = format_size(size)

        print(f"\n{vol_name}")
        print(f"  Mountpoint: {mountpoint}")
        print(f"  Total Size: {size_human}")
        print(f"  Top 10 directories:")

        top_dirs = get_top_directories(mountpoint, 10)
        if top_dirs:
            for size_str, path in reversed(top_dirs):
                # Make path relative to mountpoint for readability
                rel_path = path.replace(mountpoint, '.', 1)
                print(f"    {size_str:10s}  {rel_path}")
        else:
            print("    (empty or inaccessible)")

    print("\n" + "=" * 60)
    print(f"Total volume usage: {format_size(total_size)}")


if __name__ == "__main__":
    main()
