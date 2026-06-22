# Cachyos Forgejo

Self-hosted Forgejo instance managed via Docker Compose.

## Quick Start

```bash
# Start Forgejo
just start
# or
docker-compose up -d

# Check status
just status
# or
docker-compose ps
```

Forgejo is accessible at **https://cachyos-framework** after first start.
On first visit, complete the installation wizard to configure your instance.

## SSH Access

Forgejo's SSH is mapped to port **2222** (to avoid conflicts with the system SSH).

### Configure SSH for convenience

Add this to your `~/.ssh/config`:

```
Host cachyos-framework-forgejo
    HostName cachyos-framework
    Port 2222
    User git
```

Then you can clone repositories simply as:

```bash
git clone cachyos-framework-forgejo:username/repo.git
```

### Alternative: Specify port directly

```bash
git clone ssh://git@cachyos-framework:2222/username/repo.git
```

### HTTPS (no port change needed)

```bash
git clone https://cachyos-framework/username/repo.git
```

## Backup & Restore

This repository includes automated backup and restore scripts.

### Using `just` commands

```bash
# Full backup (data + forgejo dump)
just backup

# Quick backup (data only, no forgejo dump)
just quick-backup

# List available backups
just list-backups

# Restore from latest backup (stops and restarts Forgejo)
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
# Forgejo data directory (default: /srv/forgejo)
export FORGEJO_HOME="/srv/forgejo"

# Backup directory (default: ./backups)
# Use --backup-dir flag or modify justfile
```

## GitHub Migration

To migrate repositories from GitHub to this Forgejo instance:

```bash
# Set required environment variables
export GITHUB_USERNAME=your-github-username
export GITHUB_TOKEN=your-github-token
export FORGEJO_URL=https://cachyos-framework
export FORGEJO_TOKEN=your-forgejo-token

python migrate-github-to-forgejo.py
```

## Just Recipes

| Command | Description |
|---------|-------------|
| `just start` | Start Forgejo with docker-compose |
| `just stop` | Stop Forgejo |
| `just restart` | Restart Forgejo |
| `just logs` | Follow Forgejo logs |
| `just status` | Show container status |
| `just backup` | Create full backup |
| `just restore-full` | Stop, restore from latest backup, start |
| `just list-backups` | List available backups |
| `just du-backups` | Show backup disk usage |

## Project Structure

```
.
├── docker-compose.yml              # Docker Compose configuration
├── justfile                        # Just command recipes
├── migrate-github-to-forgejo.py    # GitHub → Forgejo migration script
├── scripts/
│   ├── backup.py                  # Backup script
│   └── restore.py                 # Restore script
└── backups/                       # Backup storage directory (created on first run)
```

## Ports

| Service | Host Port | Container Port |
|---------|-----------|----------------|
| HTTP | 80 | 80 |
| HTTPS | 443 | 443 |
| SSH | 2222 | 22 |
