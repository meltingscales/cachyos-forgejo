#!/usr/bin/env python3
"""
GitLab Restore Script

Restores a self-hosted GitLab instance from a backup.
Restores configuration, data, and database.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
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


def stop_gitlab(container_name: str | None) -> None:
    """Stop the GitLab container."""
    if container_name:
        log_info(f"Stopping GitLab container: {container_name}")
        run_command(["docker", "stop", container_name], check=False)
    else:
        log_warning("No GitLab container found to stop")


def start_gitlab() -> None:
    """Start GitLab using docker-compose."""
    repo_root = Path(__file__).parent.parent
    compose_file = repo_root / "docker-compose.yml"

    if compose_file.exists():
        log_info("Starting GitLab with docker-compose...")
        run_command([
            "docker-compose", "-f", str(compose_file), "up", "-d"
        ])
    else:
        log_warning("docker-compose.yml not found, attempting to start container...")
        run_command(["docker", "start", "gitlab"], check=False)


def extract_backup(archive_path: Path, extract_dir: Path) -> Path:
    """Extract the backup archive."""
    log_info(f"Extracting backup: {archive_path}")

    if not archive_path.exists():
        log_error(f"Backup file not found: {archive_path}")
        sys.exit(1)

    # Create extraction directory
    extract_dir.mkdir(parents=True, exist_ok=True)

    # Extract the archive
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=extract_dir.parent)

    log_success(f"Extracted to: {extract_dir}")
    return extract_dir


def restore_directories(extract_dir: Path, gitlab_home: Path, force: bool = False) -> None:
    """Restore GitLab directories from the extracted backup."""
    log_info("Restoring GitLab directories...")

    # Backup directories to restore
    dirs_to_restore = ["config", "data"]

    for dir_name in dirs_to_restore:
        src_dir = extract_dir / dir_name
        dest_dir = gitlab_home / dir_name

        if not src_dir.exists():
            log_warning(f"Directory not in backup: {dir_name}")
            continue

        # Create destination parent directory if needed
        dest_dir.parent.mkdir(parents=True, exist_ok=True)

        # Handle existing directory
        if dest_dir.exists():
            if not force:
                response = input(
                    f"{Colors.YELLOW}Directory {dest_dir} already exists. "
                    f"Replace it? [y/N]: {Colors.RESET}"
                )
                if response.lower() != "y":
                    log_warning(f"Skipping {dir_name}")
                    continue

            log_info(f"Removing existing directory: {dest_dir}")
            shutil.rmtree(dest_dir)

        log_info(f"Restoring {dir_name}...")
        shutil.copytree(src_dir, dest_dir)
        log_success(f"Restored {dir_name} to {dest_dir}")

    # Restore logs if present
    logs_dir = extract_dir / "logs"
    if logs_dir.exists():
        dest_logs = gitlab_home / "logs"
        if dest_logs.exists():
            if not force:
                response = input(
                    f"{Colors.YELLOW}Directory {dest_logs} already exists. "
                    f"Replace it? [y/N]: {Colors.RESET}"
                )
                if response.lower() != "y":
                    log_warning("Skipping logs")
                    return

            shutil.rmtree(dest_logs)
        shutil.copytree(logs_dir, dest_logs)
        log_success(f"Restored logs to {dest_logs}")


def restore_database(
    db_backup_path: Path,
    container_name: str | None,
    force: bool = False,
) -> bool:
    """Restore the GitLab database from a backup file."""
    if not db_backup_path.exists():
        log_error(f"Database backup not found: {db_backup_path}")
        return False

    if not container_name:
        log_error("GitLab container not found, cannot restore database")
        return False

    log_info(f"Restoring database from: {db_backup_path}")

    if not force:
        response = input(
            f"{Colors.YELLOW}{Colors.BOLD}This will replace the current database. "
            f"Are you sure? [y/N]: {Colors.RESET}"
        )
        if response.lower() != "y":
            log_warning("Database restore cancelled")
            return False

    # Copy backup to container
    container_backup_path = "/var/opt/gitlab/backups/"
    backup_filename = db_backup_path.name

    log_info("Copying database backup to container...")
    run_command([
        "docker", "cp",
        str(db_backup_path),
        f"{container_name}:{container_backup_path}{backup_filename}"
    ])

    # Set proper permissions
    run_command([
        "docker", "exec", container_name,
        "chown", "git:git", f"{container_backup_path}{backup_filename}"
    ])

    # Run the restore command
    log_info("Restoring database (this may take a while)...")
    result = run_command([
        "docker", "exec", container_name,
        "gitlab-rake", "gitlab:backup:restore", f"BACKUP={backup_filename.rsplit('.', 1)[0]}"
    ], check=False)

    if result.returncode == 0:
        log_success("Database restored successfully")
        return True
    else:
        log_error("Database restore failed")
        return False


def list_available_backups(backup_dir: Path) -> list[Path]:
    """List available backup archives."""
    backups = sorted(
        backup_dir.glob("gitlab-backup-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    return backups


def list_available_db_backups(backup_dir: Path) -> list[Path]:
    """List available database backup files."""
    backups = sorted(
        backup_dir.glob("gitlab-db-backup-*.tar"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    return backups


def main():
    parser = argparse.ArgumentParser(
        description="Restore a self-hosted GitLab instance from backup"
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("./backups"),
        help="Directory containing backups (default: ./backups)"
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="Specific backup archive to restore"
    )
    parser.add_argument(
        "--db-backup",
        type=Path,
        default=None,
        help="Specific database backup to restore"
    )
    parser.add_argument(
        "--gitlab-home",
        type=Path,
        default=None,
        help="GITLAB_HOME directory (default: $GITLAB_HOME or /srv/gitlab)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts"
    )
    parser.add_argument(
        "--no-db-restore",
        action="store_true",
        help="Skip database restore"
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop GitLab before restore"
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start GitLab after restore"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available backups"
    )

    args = parser.parse_args()

    # Handle list command
    if args.list:
        backup_dir = args.backup_dir
        if not backup_dir.exists():
            log_error(f"Backup directory not found: {backup_dir}")
            sys.exit(1)

        print(f"\n{Colors.BOLD}Available backups in {backup_dir}:{Colors.RESET}\n")

        archives = list_available_backups(backup_dir)
        if archives:
            print(f"{Colors.BOLD}Archive backups:{Colors.RESET}")
            for i, backup in enumerate(archives, 1):
                mtime = backup.stat().st_mtime
                size_gb = backup.stat().st_size / (1024**3)
                import datetime
                dt = datetime.datetime.fromtimestamp(mtime)
                print(f"  {i}. {backup.name} ({dt.strftime('%Y-%m-%d %H:%M:%S')}, {size_gb:.2f} GB)")
        else:
            log_warning("No archive backups found")

        db_backups = list_available_db_backups(backup_dir)
        if db_backups:
            print(f"\n{Colors.BOLD}Database backups:{Colors.RESET}")
            for i, backup in enumerate(db_backups, 1):
                mtime = backup.stat().st_mtime
                size_mb = backup.stat().st_size / (1024**2)
                import datetime
                dt = datetime.datetime.fromtimestamp(mtime)
                print(f"  {i}. {backup.name} ({dt.strftime('%Y-%m-%d %H:%M:%S')}, {size_mb:.2f} MB)")
        else:
            log_warning("No database backups found")

        sys.exit(0)

    # Get paths
    gitlab_home = args.gitlab_home or get_gitlab_home()
    backup_dir = args.backup_dir

    if not backup_dir.exists():
        log_error(f"Backup directory not found: {backup_dir}")
        sys.exit(1)

    # Determine which backup to restore
    if args.archive:
        archive_path = args.archive
    else:
        archives = list_available_backups(backup_dir)
        if not archives:
            log_error("No backups found")
            sys.exit(1)
        archive_path = archives[0]

    # Determine which database backup to restore
    db_backup_path = None
    if not args.no_db_restore:
        if args.db_backup:
            db_backup_path = args.db_backup
        else:
            db_backups = list_available_db_backups(backup_dir)
            if db_backups:
                db_backup_path = db_backups[0]

    print(f"\n{Colors.BOLD}{'=' * 50}{Colors.RESET}")
    print(f"{Colors.BOLD}GitLab Restore{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 50}{Colors.RESET}\n")
    print(f"Archive: {archive_path}")
    if db_backup_path:
        print(f"Database: {db_backup_path}")
    print(f"Target: {gitlab_home}")
    print()

    # Check Docker
    if not check_docker_running():
        log_error("Docker is not running or not accessible")
        sys.exit(1)

    # Get GitLab container
    container_name = get_gitlab_container_name()
    if container_name:
        log_info(f"Found GitLab container: {container_name}")
    else:
        log_warning("Could not find running GitLab container")

    # Stop GitLab if requested
    if args.stop and container_name:
        stop_gitlab(container_name)

    # Extract backup
    temp_dir = backup_dir / f"temp-restore-{archive_path.stem}"
    try:
        extract_dir = extract_backup(archive_path, temp_dir)

        # Restore directories
        restore_directories(extract_dir, gitlab_home, force=args.force)

        # Restore database
        if not args.no_db_restore and db_backup_path and container_name:
            restore_database(db_backup_path, container_name, force=args.force)

    finally:
        # Clean up temp directory
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

    # Start GitLab if requested
    if args.start:
        start_gitlab()

    print(f"\n{Colors.BOLD}{Colors.GREEN}Restore complete!{Colors.RESET}")
    print(f"{Colors.YELLOW}Remember to verify your GitLab instance is working correctly.{Colors.RESET}")


if __name__ == "__main__":
    main()
