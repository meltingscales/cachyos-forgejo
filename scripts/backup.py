#!/usr/bin/env python3
"""
Forgejo Backup Script

Backs up a self-hosted Forgejo instance running in Docker.
Backs up data directory and optionally runs `forgejo dump` for a complete dump.
"""

import argparse
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def log_info(message: str) -> None:
    """Print an info message."""
    print(f"{Colors.BLUE}[INFO]{Colors.RESET} {message}")


def log_success(message: str) -> None:
    """Print a success message."""
    print(f"{Colors.GREEN}[SUCCESS]{Colors.RESET} {message}")


def log_warning(message: str) -> None:
    """Print a warning message."""
    print(f"{Colors.YELLOW}[WARNING]{Colors.RESET} {message}")


def log_error(message: str) -> None:
    """Print an error message."""
    print(f"{Colors.RED}[ERROR]{Colors.RESET} {message}")


def run_command(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    log_info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        log_error(f"Command failed: {result.stderr}")
        sys.exit(1)
    return result


def get_forgejo_home() -> Path:
    """Get the FORGEJO_HOME directory from environment or default."""
    forgejo_home = os.environ.get("FORGEJO_HOME", "/srv/forgejo")
    return Path(forgejo_home)


def check_docker_compose_running() -> bool:
    """Check if Forgejo Docker Compose services are running."""
    try:
        result = run_command(
            ["docker", "compose", "ps", "--services", "--filter", "status=running"],
            check=False
        )
        # Check if any Forgejo service is running
        return bool(result.stdout.strip())
    except Exception:
        return False


def check_docker_running() -> bool:
    """Check if Docker is running and accessible."""
    try:
        result = run_command(["docker", "info"], check=False)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_forgejo_container_name() -> str | None:
    """Get the name of the running Forgejo container."""
    try:
        result = run_command(
            ["docker", "ps", "--filter", "ancestor=codeberg.org/forgejo/forgejo:14", "--format", "{{.Names}}"],
            check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
        # Fallback: search by container name
        result = run_command(
            ["docker", "ps", "--filter", "name=forgejo", "--format", "{{.Names}}"],
            check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass
    return None


def create_backup_directory(backup_dir: Path) -> Path:
    """Create the backup directory if it doesn't exist."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def create_backup_archive(
    forgejo_home: Path,
    backup_dir: Path,
    timestamp: str,
    include_logs: bool = False,
) -> Path:
    """Create a compressed archive of Forgejo data."""
    archive_name = f"forgejo-backup-{timestamp}"
    archive_path = backup_dir / f"{archive_name}.tar.gz"

    log_info(f"Creating backup archive: {archive_path}")

    # Forgejo stores everything under the data volume root
    dirs_to_backup = [
        (forgejo_home / "gitea", "gitea"),   # config and internal data
        (forgejo_home / "git", "git"),        # git repositories
        (forgejo_home / "ssh", "ssh"),        # SSH host keys
    ]

    optional_dirs = ["avatars", "attachments", "lfs", "packages"]
    for d in optional_dirs:
        if (forgejo_home / d).exists():
            dirs_to_backup.append((forgejo_home / d, d))

    if include_logs:
        if (forgejo_home / "log").exists():
            dirs_to_backup.append((forgejo_home / "log", "log"))

    # Create temporary directory for structured backup
    temp_dir = backup_dir / f"{archive_name}-temp"
    temp_dir.mkdir(exist_ok=True)

    try:
        for src_dir, dir_name in dirs_to_backup:
            if not src_dir.exists():
                log_warning(f"Source directory does not exist: {src_dir}")
                continue

            dest_dir = temp_dir / dir_name
            log_info(f"Copying {dir_name}...")

            try:
                run_command([
                    "rsync", "-a", "--delete",
                    str(src_dir) + "/", str(dest_dir) + "/"
                ], check=False)
            except (FileNotFoundError, subprocess.SubprocessError):
                shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)

        # Create metadata file
        metadata = {
            "timestamp": timestamp,
            "forgejo_home": str(forgejo_home),
            "include_logs": include_logs,
            "backup_type": "full",
        }

        metadata_path = temp_dir / "backup_metadata.txt"
        with open(metadata_path, "w") as f:
            for key, value in metadata.items():
                f.write(f"{key}={value}\n")

        log_info("Compressing backup...")
        run_command([
            "tar", "-czf", str(archive_path),
            "-C", str(temp_dir.parent),
            temp_dir.name
        ])

        log_success(f"Backup created: {archive_path}")
        return archive_path

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def create_forgejo_dump(
    container_name: str,
    backup_dir: Path,
    timestamp: str,
) -> Path | None:
    """Create a Forgejo dump using the built-in dump command."""
    dump_file = backup_dir / f"forgejo-dump-{timestamp}.zip"

    log_info("Creating Forgejo dump...")

    result = run_command([
        "docker", "exec", "-u", "git", container_name,
        "forgejo", "dump",
        "--config", "/data/gitea/conf/app.ini",
        "--file", f"/tmp/forgejo-dump-{timestamp}.zip",
        "--type", "zip",
    ], check=False)

    if result.returncode != 0:
        log_warning("Forgejo dump command failed, continuing without dump...")
        return None

    copy_result = run_command([
        "docker", "cp",
        f"{container_name}:/tmp/forgejo-dump-{timestamp}.zip",
        str(dump_file)
    ], check=False)

    # Clean up temp file in container
    run_command([
        "docker", "exec", container_name,
        "rm", "-f", f"/tmp/forgejo-dump-{timestamp}.zip"
    ], check=False)

    if copy_result.returncode == 0:
        log_success(f"Forgejo dump: {dump_file}")
        return dump_file

    log_warning("Could not retrieve dump file")
    return None


def cleanup_old_backups(backup_dir: Path, keep_count: int) -> None:
    """Remove old backups, keeping only the most recent ones."""
    log_info(f"Cleaning up old backups (keeping {keep_count} most recent)...")

    backups = sorted(
        backup_dir.glob("forgejo-backup-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    for old_backup in backups[keep_count:]:
        log_info(f"Removing old backup: {old_backup.name}")
        old_backup.unlink()

    dumps = sorted(
        backup_dir.glob("forgejo-dump-*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    for old_dump in dumps[keep_count:]:
        log_info(f"Removing old dump: {old_dump.name}")
        old_dump.unlink()


def main():
    parser = argparse.ArgumentParser(
        description="Backup a self-hosted Forgejo instance"
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("./backups"),
        help="Directory to store backups (default: ./backups)"
    )
    parser.add_argument(
        "--forgejo-home",
        type=Path,
        default=None,
        help="FORGEJO_HOME directory (default: $FORGEJO_HOME or /srv/forgejo)"
    )
    parser.add_argument(
        "--include-logs",
        action="store_true",
        help="Include logs in the backup (excluded by default)"
    )
    parser.add_argument(
        "--no-db-backup",
        action="store_true",
        help="Skip forgejo dump"
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=7,
        help="Number of backups to keep (default: 7)"
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Don't remove old backups"
    )

    args = parser.parse_args()

    # Safety check: ensure Docker Compose services are NOT running
    if check_docker_compose_running():
        log_error("Docker Compose services are running!")
        log_error("Please stop them first with: docker compose down")
        log_error("Or use: just stop")
        sys.exit(1)

    if not check_docker_running():
        log_error("Docker is not running or not accessible")
        sys.exit(1)

    container_name = get_forgejo_container_name()
    if not container_name:
        log_warning("Could not find running Forgejo container")
    else:
        log_info(f"Found Forgejo container: {container_name}")

    forgejo_home = args.forgejo_home or get_forgejo_home()
    log_info(f"Forgejo home: {forgejo_home}")

    if not forgejo_home.exists():
        log_error(f"Forgejo home directory not found: {forgejo_home}")
        sys.exit(1)

    backup_dir = create_backup_directory(args.backup_dir)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{Colors.BOLD}{'=' * 50}{Colors.RESET}")
    print(f"{Colors.BOLD}Forgejo Backup{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 50}{Colors.RESET}\n")

    archive_path = create_backup_archive(
        forgejo_home=forgejo_home,
        backup_dir=backup_dir,
        timestamp=timestamp,
        include_logs=args.include_logs,
    )

    dump_path = None
    if not args.no_db_backup and container_name:
        dump_path = create_forgejo_dump(
            container_name=container_name,
            backup_dir=backup_dir,
            timestamp=timestamp,
        )

    if not args.no_cleanup:
        cleanup_old_backups(backup_dir, args.keep)

    print(f"\n{Colors.BOLD}{Colors.GREEN}Backup complete!{Colors.RESET}")
    print(f"  Archive: {archive_path}")
    print(f"  Size: {archive_path.stat().st_size / (1024**3):.2f} GB")
    if dump_path:
        print(f"  Dump: {dump_path}")
        print(f"  Dump size: {dump_path.stat().st_size / (1024**2):.2f} MB")


if __name__ == "__main__":
    main()
