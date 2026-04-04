# Cachyos GitLab

Self-hosted GitLab instance managed via Docker Compose.

## Quick Start

```bash
# Start GitLab
just start
# or
docker-compose up -d

# Check status
just status
# or
docker-compose ps
```

## SSH Access

GitLab's SSH is mapped to port **2222** (to avoid conflicts with the system SSH).

### Configure SSH for convenience

Add this to your `~/.ssh/config`:

```
Host kalameet-gitlab
    HostName kalameet
    Port 2222
    User git
```

Then you can clone repositories simply as:

```bash
git clone kalameet-gitlab:username/repo.git
```

### Alternative: Specify port directly

```bash
git clone ssh://git@kalameet:2222/username/repo.git
```

### HTTPS (no port change needed)

```bash
git clone https://kalameet/username/repo.git
```

## Backup & Restore

This repository includes automated backup and restore scripts.

### Using `just` commands

```bash
# Full backup (config, data, database)
just backup

# Quick backup (config + data only, faster)
just quick-backup

# List available backups
just list-backups

# Restore from latest backup (stops and restarts GitLab)
just restore-full

# Check backup disk usage
just du-backups
```

### Using scripts directly

```bash
# Backup
./scripts/backup.py --help

# Restore
./scripts/restore.py --list
./scripts/restore.py
```

### Configuration

Set environment variables to customize:

```bash
# GitLab data directory (default: /srv/gitlab)
export GITLAB_HOME="/srv/gitlab"

# Backup directory (default: ./backups)
# Use --backup-dir flag or modify justfile
```

## Just Recipes

| Command | Description |
|---------|-------------|
| `just start` | Start GitLab with docker-compose |
| `just stop` | Stop GitLab |
| `just restart` | Restart GitLab |
| `just logs` | Follow GitLab logs |
| `just status` | Show container status |
| `just backup` | Create full backup |
| `just restore-full` | Stop, restore from latest backup, start |
| `just list-backups` | List available backups |
| `just du-backups` | Show backup disk usage |

## Project Structure

```
.
├── docker-compose.yml      # Docker Compose configuration
├── justfile                # Just command recipes
├── scripts/
│   ├── backup.py          # Backup script
│   └── restore.py         # Restore script
└── backups/               # Backup storage directory (created on first run)
```

## Ports

| Service | Host Port | Container Port |
|---------|-----------|----------------|
| HTTP | 80 | 80 |
| HTTPS | 443 | 443 |
| SSH | 2222 | 22 |
