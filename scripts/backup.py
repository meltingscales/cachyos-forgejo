#!/usr/bin/env python3
"""
GitLab Backup Script

Backs up a self-hosted GitLab instance running in Docker.
Backs up configuration, logs, data, and creates a database dump.
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


def get_gitlab_home() -> Path:
    """Get the GITLAB_HOME directory from environment or default."""
    gitlab_home = os.environ.get("GITLAB_HOME", "/srv/gitlab")
    return Path(gitlab_home)


def check_docker_running() -> bool:
    """Check if Docker is running and accessible."""
    try:
        result = run_command(["docker", "info"], check=False)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_gitlab_container_name() -> str | None:
    """Get the name of the running GitLab container."""
    try:
        result = run_command(
            ["docker", "ps", "--filter", "ancestor=gitlab/gitlab-ce", "--format", "{{.Names}}"],
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
    gitlab_home: Path,
    backup_dir: Path,
    timestamp: str,
    include_logs: bool = False,
) -> Path:
    """Create a compressed archive of GitLab data."""
    archive_name = f"gitlab-backup-{timestamp}"
    archive_path = backup_dir / f"{archive_name}.tar.gz"

    log_info(f"Creating backup archive: {archive_path}")

    # Build list of directories to backup
    dirs_to_backup = [
        (gitlab_home / "config", "config"),
        (gitlab_home / "data", "data"),
    ]

    if include_logs:
        dirs_to_backup.append((gitlab_home / "logs", "logs"))

    # Create temporary directory for structured backup
    temp_dir = backup_dir / f"{archive_name}-temp"
    temp_dir.mkdir(exist_ok=True)

    try:
        # Copy/sync directories to temp location
        for src_dir, dir_name in dirs_to_backup:
            if not src_dir.exists():
                log_warning(f"Source directory does not exist: {src_dir}")
                continue

            dest_dir = temp_dir / dir_name
            log_info(f"Copying {dir_name}...")

            # Use rsync if available, otherwise use shutil.copytree
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
            "gitlab_home": str(gitlab_home),
            "include_logs": include_logs,
            "backup_type": "full",
        }

        metadata_path = temp_dir / "backup_metadata.txt"
        with open(metadata_path, "w") as f:
            for key, value in metadata.items():
                f.write(f"{key}={value}\n")

        # Create the compressed archive
        log_info("Compressing backup...")
        run_command([
            "tar", "-czf", str(archive_path),
            "-C", str(temp_dir.parent),
            temp_dir.name
        ])

        log_success(f"Backup created: {archive_path}")
        return archive_path

    finally:
        # Clean up temp directory
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def create_database_backup(
    container_name: str,
    backup_dir: Path,
    timestamp: str,
) -> Path | None:
    """Create a GitLab database backup using the built-in rake task."""
    backup_file = backup_dir / f"gitlab-db-backup-{timestamp}.tar"

    log_info("Creating database backup using gitlab-rake...")

    # Create the backup directory inside the container
    result = run_command([
        "docker", "exec", container_name,
        "gitlab-rake", "gitlab:backup:create"
    ], check=False)

    if result.returncode != 0:
        log_warning("Database backup command failed, continuing...")
        return None

    # Find the created backup file
    # GitLab creates backups in /var/opt/gitlab/backups
    find_result = run_command([
        "docker", "exec", container_name,
        "find", "/var/opt/gitlab/backups",
        "-name", "*.tar",
        "-mtime", "-1",
        "-printf", "%T@ %p\n"
    ], check=False)

    if find_result.returncode == 0 and find_result.stdout.strip():
        # Get the most recent backup
        lines = find_result.stdout.strip().split("\n")
        if lines:
            latest_backup = sorted(lines, reverse=True)[0].split(" ", 1)[1]

            # Copy the backup from container to host
            copy_result = run_command([
                "docker", "cp",
                f"{container_name}:{latest_backup}",
                str(backup_file)
            ], check=False)

            if copy_result.returncode == 0:
                log_success(f"Database backup: {backup_file}")
                return backup_file

    log_warning("Could not retrieve database backup file")
    return None


def cleanup_old_backups(backup_dir: Path, keep_count: int) -> None:
    """Remove old backups, keeping only the most recent ones."""
    log_info(f"Cleaning up old backups (keeping {keep_count} most recent)...")

    backups = sorted(
        backup_dir.glob("gitlab-backup-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    for old_backup in backups[keep_count:]:
        log_info(f"Removing old backup: {old_backup.name}")
        old_backup.unlink()

    # Also cleanup old database backups
    db_backups = sorted(
        backup_dir.glob("gitlab-db-backup-*.tar"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    for old_backup in db_backups[keep_count:]:
        log_info(f"Removing old database backup: {old_backup.name}")
        old_backup.unlink()


def main():
    parser = argparse.ArgumentParser(
        description="Backup a self-hosted GitLab instance"
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("./backups"),
        help="Directory to store backups (default: ./backups)"
    )
    parser.add_argument(
        "--gitlab-home",
        type=Path,
        default=None,
        help="GITLAB_HOME directory (default: $GITLAB_HOME or /srv/gitlab)"
    )
    parser.add_argument(
        "--include-logs",
        action="store_true",
        help="Include logs in the backup (excluded by default)"
    )
    parser.add_argument(
        "--no-db-backup",
        action="store_true",
        help="Skip database backup using gitlab-rake"
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

    # Validate Docker is running
    if not check_docker_running():
        log_error("Docker is not running or not accessible")
        sys.exit(1)

    # Get GitLab container
    container_name = get_gitlab_container_name()
    if not container_name:
        log_warning("Could not find running GitLab container")
    else:
        log_info(f"Found GitLab container: {container_name}")

    # Get paths
    gitlab_home = args.gitlab_home or get_gitlab_home()
    log_info(f"GitLab home: {gitlab_home}")

    # Verify GitLab directories exist
    if not (gitlab_home / "config").exists():
        log_error(f"GitLab config directory not found: {gitlab_home / 'config'}")
        sys.exit(1)

    # Create backup directory
    backup_dir = create_backup_directory(args.backup_dir)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{Colors.BOLD}{'=' * 50}{Colors.RESET}")
    print(f"{Colors.BOLD}GitLab Backup{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 50}{Colors.RESET}\n")

    # Create filesystem backup
    archive_path = create_backup_archive(
        gitlab_home=gitlab_home,
        backup_dir=backup_dir,
        timestamp=timestamp,
        include_logs=args.include_logs,
    )

    # Create database backup
    db_backup_path = None
    if not args.no_db_backup and container_name:
        db_backup_path = create_database_backup(
            container_name=container_name,
            backup_dir=backup_dir,
            timestamp=timestamp,
        )

    # Cleanup old backups
    if not args.no_cleanup:
        cleanup_old_backups(backup_dir, args.keep)

    # Summary
    print(f"\n{Colors.BOLD}{Colors.GREEN}Backup complete!{Colors.RESET}")
    print(f"  Archive: {archive_path}")
    print(f"  Size: {archive_path.stat().st_size / (1024**3):.2f} GB")
    if db_backup_path:
        print(f"  Database: {db_backup_path}")
        print(f"  DB Size: {db_backup_path.stat().st_size / (1024**2):.2f} MB")


if __name__ == "__main__":
    main()
