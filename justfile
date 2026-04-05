# Justfile for Forgejo backup and restore operations
# https://github.com/casey/just

# Default recipe
default:
    @just --list

# FORGEJO_HOME directory (override with: just FORGEJO_HOME=/custom/path backup)
FORGEJO_HOME := env_var_or_default("FORGEJO_HOME", "/srv/forgejo")

# Backup directory
BACKUP_DIR := "./backups"

# Number of backups to keep
KEEP := "7"

# Python interpreter
PYTHON := "python3"

# Create a full backup
backup:
    #!/usr/bin/env bash
    mkdir -p {{BACKUP_DIR}}
    {{PYTHON}} scripts/backup.py --backup-dir {{BACKUP_DIR}} --forgejo-home {{FORGEJO_HOME}} --keep {{KEEP}}

# Create a backup including logs
backup-with-logs:
    #!/usr/bin/env bash
    mkdir -p {{BACKUP_DIR}}
    {{PYTHON}} scripts/backup.py --backup-dir {{BACKUP_DIR}} --forgejo-home {{FORGEJO_HOME}} --keep {{KEEP}} --include-logs

# Quick backup (no forgejo dump)
quick-backup:
    #!/usr/bin/env bash
    mkdir -p {{BACKUP_DIR}}
    {{PYTHON}} scripts/backup.py --backup-dir {{BACKUP_DIR}} --forgejo-home {{FORGEJO_HOME}} --keep {{KEEP}} --no-db-backup

# Restore from the latest backup
restore:
    #!/usr/bin/env bash
    {{PYTHON}} scripts/restore.py --backup-dir {{BACKUP_DIR}} --forgejo-home {{FORGEJO_HOME}}

# Restore from a specific archive
restore-archive archive:
    #!/usr/bin/env bash
    {{PYTHON}} scripts/restore.py --backup-dir {{BACKUP_DIR}} --forgejo-home {{FORGEJO_HOME}} --archive {{archive}}

# Restore and stop/start Forgejo around the restore
restore-full:
    #!/usr/bin/env bash
    {{PYTHON}} scripts/restore.py --backup-dir {{BACKUP_DIR}} --forgejo-home {{FORGEJO_HOME}} --stop --start

# List available backups
list-backups:
    #!/usr/bin/env bash
    {{PYTHON}} scripts/restore.py --backup-dir {{BACKUP_DIR}} --list

# Start Forgejo using docker-compose
start:
    docker-compose up -d

# Stop Forgejo using docker-compose
stop:
    docker-compose down

# Restart Forgejo
restart:
    just stop && just start

# View Forgejo logs
logs:
    docker-compose logs -f

# View Forgejo status
status:
    docker-compose ps

# Run a backup with a confirmation prompt
safe-backup:
    #!/usr/bin/env bash
    echo "Starting backup to {{BACKUP_DIR}}..."
    read -p "Press Enter to continue or Ctrl+C to cancel..."
    just backup

# Run a restore with a confirmation prompt
safe-restore:
    #!/usr/bin/env bash
    echo "Restoring from {{BACKUP_DIR}}..."
    read -p "Press Enter to continue or Ctrl+C to cancel..."
    just restore-full

# Clean all backups (use with caution!)
clean-backups:
    #!/usr/bin/env bash
    read -p "Are you sure you want to delete ALL backups in {{BACKUP_DIR}}? [yes/NO]: " confirm
    if [ "$confirm" = "yes" ]; then
        rm -rf {{BACKUP_DIR}}/*
        echo "All backups deleted."
    else
        echo "Cancelled."
    fi

# Show disk usage of backups
du-backups:
    #!/usr/bin/env bash
    if [ -d "{{BACKUP_DIR}}" ]; then
        du -sh {{BACKUP_DIR}}
        echo ""
        echo "Individual backups:"
        du -sh {{BACKUP_DIR}}/* 2>/dev/null || echo "No backups found."
    else
        echo "Backup directory does not exist: {{BACKUP_DIR}}"
    fi

# Show Docker Compose volume usage
volume-usage:
    #!/usr/bin/env bash
    {{PYTHON}} scripts/volume-usage.py

# Make scripts executable
setup:
    chmod +x scripts/backup.py scripts/restore.py scripts/volume-usage.py
    mkdir -p {{BACKUP_DIR}}
    echo "Setup complete. Scripts are now executable."

# Migrate GitHub repositories to Forgejo
migrate-github:
    #!/usr/bin/env bash
    if [ ! -f ".env" ]; then
        echo "Error: .env file not found"
        echo "Create a .env file with:"
        echo "  GITHUB_USERNAME=your_username"
        echo "  GITHUB_TOKEN=your_github_token"
        echo "  FORGEJO_URL=https://kalameet"
        echo "  FORGEJO_TOKEN=your_forgejo_token"
        exit 1
    fi
    uv run migrate-github-to-forgejo.py

# Migrate GitHub repos (include forks)
migrate-github-all:
    #!/usr/bin/env bash
    if [ ! -f ".env" ]; then
        echo "Error: .env file not found"
        echo "Create a .env file with:"
        echo "  GITHUB_USERNAME=your_username"
        echo "  GITHUB_TOKEN=your_github_token"
        echo "  FORGEJO_URL=https://kalameet"
        echo "  FORGEJO_TOKEN=your_forgejo_token"
        exit 1
    fi
    INCLUDE_FORKS=true uv run migrate-github-to-forgejo.py

# Verify backup integrity (extracts to temp and checks)
verify-backup archive:
    #!/usr/bin/env bash
    temp_dir=$(mktemp -d)
    echo "Extracting {{archive}} to verify..."
    if tar -tzf {{archive}} > /dev/null 2>&1; then
        echo "✓ Archive is valid and can be extracted."
        tar -xzf {{archive}} -C "$temp_dir"
        echo "✓ Successfully extracted to: $temp_dir"
        echo ""
        echo "Contents:"
        ls -la "$temp_dir"
        echo ""
        read -p "Press Enter to clean up temp directory..."
        rm -rf "$temp_dir"
    else
        echo "✗ Archive is corrupted or invalid."
        rm -rf "$temp_dir"
        exit 1
    fi
