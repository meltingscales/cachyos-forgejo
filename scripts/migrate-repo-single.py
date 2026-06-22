#!/usr/bin/env python3
"""
migrate-repo-single.py

Mirror-clone a single Git remote and push it to a self-hosted Forgejo instance.

Usage:
    python migrate-repo-single.py --remote <git-url> [--name <repo-name>] [--private]

Variables can be set in a .env file or as environment variables.

Required variables:
    FORGEJO_URL    Base URL of the target Forgejo instance (e.g. https://forgejo.example.com)
    FORGEJO_TOKEN  Forgejo personal access token (needs write:repository scope)

Optional variables:
    FORGEJO_SSH_PORT  SSH port for Forgejo (default: 2222)
    CA_CERT           Path to CA cert for self-signed TLS (default: caddy-ca.crt)
    VERIFY_SSL        Set to 'false' to skip SSL verification (default: true)
"""

import argparse
import os
import subprocess
import sys
from urllib.parse import urlparse

import requests

if os.path.exists('.env'):
    from dotenv import load_dotenv
    load_dotenv()

WORKSPACE = "./migration-workspace/"
FORGEJO_URL = os.getenv('FORGEJO_URL', '').rstrip('/')
FORGEJO_TOKEN = os.getenv('FORGEJO_TOKEN')
FORGEJO_SSH_PORT = os.getenv('FORGEJO_SSH_PORT', '2222')

CA_CERT = os.getenv('CA_CERT', 'caddy-ca.crt')
VERIFY_SSL = os.getenv('VERIFY_SSL', 'true').lower() == 'true'
VERIFY = CA_CERT if VERIFY_SSL and os.path.exists(CA_CERT) else VERIFY_SSL


def forgejo_headers():
    return {
        'Authorization': f'token {FORGEJO_TOKEN}',
        'Content-Type': 'application/json',
    }


def get_forgejo_username():
    r = requests.get(f'{FORGEJO_URL}/api/v1/user', headers=forgejo_headers(), verify=VERIFY)
    if r.status_code != 200:
        print(f"Error fetching Forgejo user (HTTP {r.status_code}): {r.text}", file=sys.stderr)
        sys.exit(1)
    return r.json()['login']


def repo_name_from_url(url):
    """Derive a repo name from any git URL."""
    path = urlparse(url).path
    if not path:
        # SCP-style: git@host:user/repo.git
        path = url.split(':')[-1]
    name = os.path.basename(path)
    if name.endswith('.git'):
        name = name[:-4]
    return name


def get_or_create_forgejo_repo(forgejo_username, repo_name, is_private):
    r = requests.get(
        f'{FORGEJO_URL}/api/v1/repos/{forgejo_username}/{repo_name}',
        headers=forgejo_headers(),
        verify=VERIFY,
    )
    if r.status_code == 200:
        print(f"  Forgejo repo already exists: {forgejo_username}/{repo_name}")
        return r.json()['clone_url']

    payload = {
        'name': repo_name,
        'private': is_private,
        'auto_init': False,
    }
    r = requests.post(
        f'{FORGEJO_URL}/api/v1/user/repos',
        headers=forgejo_headers(),
        json=payload,
        verify=VERIFY,
    )
    if r.status_code not in (200, 201):
        print(f"  Error creating Forgejo repo (HTTP {r.status_code}): {r.text}", file=sys.stderr)
        return None

    visibility = 'private' if is_private else 'public'
    print(f"  Created Forgejo repo: {forgejo_username}/{repo_name} ({visibility})")
    return r.json()['clone_url']


def forgejo_push_url(clone_url):
    parsed = urlparse(clone_url)
    path = parsed.path.lstrip('/')
    host = FORGEJO_URL.removeprefix('https://').removeprefix('http://')
    return f'ssh://git@{host}:{FORGEJO_SSH_PORT}/{path}'


def run(cmd, cwd=None, label=''):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Error running {label or ' '.join(cmd)}:", file=sys.stderr)
        if result.stderr:
            print(f"  {result.stderr.strip()}", file=sys.stderr)
    return result.returncode == 0


def mirror_or_update(remote_url, local_path):
    if os.path.exists(local_path):
        print("  Updating existing mirror...")
        return run(['git', 'remote', 'update', '--prune'], cwd=local_path, label='git remote update')
    print("  Cloning mirror...")
    return run(['git', 'clone', '--mirror', remote_url, local_path], label='git clone --mirror')


def push_mirror(local_path, push_url):
    print("  Pushing to Forgejo...")
    result = subprocess.run(
        ['git', 'push', '--mirror', push_url],
        cwd=local_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr
        if 'remote rejected' in stderr and 'hidden ref' in stderr:
            if any(x in stderr for x in ['->', '[new branch]', '[new tag]']):
                print("  Note: some hidden refs skipped (e.g. GitHub PR refs)")
                return True
        print(f"  Push failed:\n  {stderr.strip()}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description='Mirror a single Git repo to Forgejo')
    parser.add_argument('--remote', required=True, help='Source git remote URL')
    parser.add_argument('--name', help='Override repo name on Forgejo (default: derived from URL)')
    parser.add_argument('--private', action='store_true', default=True,
                        help='Create as private (default: true)')
    parser.add_argument('--public', dest='private', action='store_false',
                        help='Create as public')
    args = parser.parse_args()

    missing = [v for v in ('FORGEJO_URL', 'FORGEJO_TOKEN') if not os.getenv(v)]
    if missing:
        print(f"Error: missing environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    repo_name = args.name or repo_name_from_url(args.remote)
    if not repo_name:
        print("Error: could not derive repo name from URL; use --name", file=sys.stderr)
        sys.exit(1)

    os.makedirs(WORKSPACE, exist_ok=True)
    local_path = os.path.join(WORKSPACE, repo_name + '.git')

    print(f"Migrating: {args.remote}")
    print(f"  Forgejo URL : {FORGEJO_URL}")
    print(f"  Repo name   : {repo_name}")
    print(f"  Workspace   : {os.path.abspath(WORKSPACE)}")
    print()

    forgejo_username = get_forgejo_username()

    if not mirror_or_update(args.remote, local_path):
        sys.exit(1)

    clone_url = get_or_create_forgejo_repo(forgejo_username, repo_name, args.private)
    if not clone_url:
        sys.exit(1)

    push_url = forgejo_push_url(clone_url)
    if not push_mirror(local_path, push_url):
        sys.exit(1)

    print(f"\nDone: {repo_name} -> {FORGEJO_URL}/{forgejo_username}/{repo_name}")


if __name__ == '__main__':
    main()
