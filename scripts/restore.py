#!/usr/bin/env python3
"""
Forgejo Restore Script

Restores a self-hosted Forgejo instance from a backup.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from tqdm import tqdm


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
        result = run_command(
            ["docker", "ps", "--filter", "name=forgejo", "--format", "{{.Names}}"],
            check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass
    return None


def stop_forgejo(container_name: str | None) -> None:
    """Stop the Forgejo container."""
    if container_name:
        log_info(f"Stopping Forgejo container: {container_name}")
        run_command(["docker", "stop", container_name], check=False)
    else:
        log_warning("No Forgejo container found to stop")


def start_forgejo() -> None:
    """Start Forgejo using docker-compose."""
    repo_root = Path(__file__).parent.parent
    compose_file = repo_root / "docker-compose.yml"

    if compose_file.exists():
        log_info("Starting Forgejo with docker-compose...")
        run_command([
            "docker-compose", "-f", str(compose_file), "up", "-d"
        ])
    else:
        log_warning("docker-compose.yml not found, attempting to start container...")
        run_command(["docker", "start", "forgejo"], check=False)


def extract_backup(archive_path: Path, extract_dir: Path) -> Path:
    """Extract the backup archive."""
    log_info(f"Extracting backup: {archive_path}")

    if not archive_path.exists():
        log_error(f"Backup file not found: {archive_path}")
        sys.exit(1)

    extract_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        members = tar.getmembers()
        with tqdm(total=len(members), desc="Extracting", unit="file") as pbar:
            for member in members:
                tar.extract(member, path=extract_dir.parent, filter="tar")
                pbar.update(1)

    log_success(f"Extracted to: {extract_dir}")
    return extract_dir


def restore_directories(extract_dir: Path, forgejo_home: Path, force: bool = False) -> None:
    """Restore Forgejo directories from the extracted backup."""
    log_info("Restoring Forgejo directories...")

    dirs_to_restore = ["gitea", "git", "ssh", "avatars", "attachments", "lfs", "packages", "log"]

    for dir_name in tqdm(dirs_to_restore, desc="Restoring directories", unit="dir"):
        src_dir = extract_dir / dir_name
        dest_dir = forgejo_home / dir_name

        if not src_dir.exists():
            continue

        dest_dir.parent.mkdir(parents=True, exist_ok=True)

        if dest_dir.exists():
            if not force:
                tqdm.write("")
                response = input(
                    f"{Colors.YELLOW}Directory {dest_dir} already exists. "
                    f"Replace it? [y/N]: {Colors.RESET}"
                )
                if response.lower() != "y":
                    tqdm.write(f"{Colors.YELLOW}[WARNING]{Colors.RESET} Skipping {dir_name}")
                    continue

            tqdm.write(f"{Colors.BLUE}[INFO]{Colors.RESET} Removing existing directory: {dest_dir}")
            shutil.rmtree(dest_dir)

        tqdm.write(f"{Colors.BLUE}[INFO]{Colors.RESET} Restoring {dir_name}...")
        shutil.copytree(src_dir, dest_dir)
        tqdm.write(f"{Colors.GREEN}[SUCCESS]{Colors.RESET} Restored {dir_name} to {dest_dir}")


def list_available_backups(backup_dir: Path) -> list[Path]:
    """List available backup archives."""
    backups = sorted(
        backup_dir.glob("forgejo-backup-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    return backups


def main():
    parser = argparse.ArgumentParser(
        description="Restore a self-hosted Forgejo instance from backup"
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
        "--forgejo-home",
        type=Path,
        default=None,
        help="FORGEJO_HOME directory (default: $FORGEJO_HOME or /srv/forgejo)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts"
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop Forgejo before restore"
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start Forgejo after restore"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available backups"
    )

    args = parser.parse_args()

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

        sys.exit(0)

    forgejo_home = args.forgejo_home or get_forgejo_home()
    backup_dir = args.backup_dir

    if not backup_dir.exists():
        log_error(f"Backup directory not found: {backup_dir}")
        sys.exit(1)

    if args.archive:
        archive_path = args.archive
    else:
        archives = list_available_backups(backup_dir)
        if not archives:
            log_error("No backups found")
            sys.exit(1)
        archive_path = archives[0]

    print(f"\n{Colors.BOLD}{'=' * 50}{Colors.RESET}")
    print(f"{Colors.BOLD}Forgejo Restore{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 50}{Colors.RESET}\n")
    print(f"Archive: {archive_path}")
    print(f"Target: {forgejo_home}")
    print()

    # Safety check: ensure Docker Compose services are NOT running
    if check_docker_compose_running():
        log_error("Docker Compose services are running!")
        log_error("Please stop them first with: docker compose down")
        log_error("Or use: just stop")
        log_error("Or use --stop flag to stop them before restore")
        sys.exit(1)

    if not check_docker_running():
        log_error("Docker is not running or not accessible")
        sys.exit(1)

    container_name = get_forgejo_container_name()
    if container_name:
        log_info(f"Found Forgejo container: {container_name}")
    else:
        log_warning("Could not find running Forgejo container")

    if args.stop and container_name:
        stop_forgejo(container_name)

    temp_dir = backup_dir / f"temp-restore-{archive_path.stem}"
    try:
        extract_dir = extract_backup(archive_path, temp_dir)
        restore_directories(extract_dir, forgejo_home, force=args.force)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

    if args.start:
        start_forgejo()

    print(f"\n{Colors.BOLD}{Colors.GREEN}Restore complete!{Colors.RESET}")
    print(f"{Colors.YELLOW}Remember to verify your Forgejo instance is working correctly.{Colors.RESET}")


if __name__ == "__main__":
    main()
