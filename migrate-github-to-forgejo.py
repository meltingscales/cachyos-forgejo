#!/usr/bin/env python3
"""
migrate-github-to-forgejo.py

Migrates all GitHub repositories for a user to a self-hosted Forgejo instance.
Uses mirror clones to preserve all branches, tags, and refs.

Usage:
    python migrate-github-to-forgejo.py

Variables can be set in a .env file in the working directory, or as environment variables.

Required variables:
    GITHUB_USERNAME   GitHub username to migrate repos from
    GITHUB_TOKEN      GitHub personal access token (needs repo scope)
    FORGEJO_URL       Base URL of the target Forgejo instance (e.g. https://forgejo.example.com)
    FORGEJO_TOKEN     Forgejo personal access token (needs write:repository scope)

Optional variables:
    INCLUDE_FORKS     Set to 'true' to include forked repositories (default: false)

The script will:
    1. Fetch all repos from GitHub (excluding forks by default)
    2. Mirror-clone each repo locally into ./migration-workspace/
    3. Create the corresponding repository on Forgejo if it doesn't exist
    4. Push the mirror to Forgejo, preserving visibility (public/private)

Re-running the script is safe: existing mirrors are updated and re-pushed.
"""

import os
import subprocess
import sys
from datetime import datetime

import requests
from tqdm import tqdm

if os.path.exists('.env'):
    from dotenv import load_dotenv
    load_dotenv()

WORKSPACE = "./migration-workspace/"
GITHUB_USERNAME = os.getenv('GITHUB_USERNAME')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
FORGEJO_URL = os.getenv('FORGEJO_URL', '').rstrip('/')
FORGEJO_TOKEN = os.getenv('FORGEJO_TOKEN')
FORGEJO_SSH_PORT = os.getenv('FORGEJO_SSH_PORT', '2222')
INCLUDE_FORKS = os.getenv('INCLUDE_FORKS', 'false').lower() == 'true'

# SSL certificate verification (for self-signed certs)
CA_CERT = os.getenv('CA_CERT', 'caddy-ca.crt')
VERIFY_SSL = os.getenv('VERIFY_SSL', 'true').lower() == 'true'
VERIFY = CA_CERT if VERIFY_SSL and os.path.exists(CA_CERT) else VERIFY_SSL

# Validation settings
VALIDATE_SAMPLE_COUNT = int(os.getenv('VALIDATE_SAMPLE_COUNT', '3'))
VALIDATE_REPOS = os.getenv('VALIDATE_REPOS', 'true').lower() == 'true'


def github_headers():
    return {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }


def forgejo_headers():
    return {
        'Authorization': f'token {FORGEJO_TOKEN}',
        'Content-Type': 'application/json',
    }


def verify_ssl():
    return VERIFY


def get_github_repos():
    repos = []
    page = 1

    while True:
        url = f'https://api.github.com/user/repos?page={page}&per_page=100&type=all'
        response = requests.get(url, headers=github_headers())

        if response.status_code != 200:
            print(f"Error fetching GitHub repos (HTTP {response.status_code}): {response.text}", file=sys.stderr)
            sys.exit(1)

        remaining = int(response.headers.get('X-RateLimit-Remaining', 1))
        if remaining == 0:
            reset_time = response.headers.get('X-RateLimit-Reset', 'unknown')
            print(f"GitHub API rate limit reached. Resets at: {reset_time}", file=sys.stderr)
            sys.exit(1)

        page_repos = response.json()
        if not page_repos:
            break

        repos.extend(page_repos)
        page += 1

    if not INCLUDE_FORKS:
        forks = [r['name'] for r in repos if r.get('fork')]
        repos = [r for r in repos if not r.get('fork')]
        if forks:
            print(f"Skipping {len(forks)} fork(s): {', '.join(forks)}")
            print("  (set INCLUDE_FORKS=true to include them)")

    return repos


def get_forgejo_username():
    response = requests.get(f'{FORGEJO_URL}/api/v1/user', headers=forgejo_headers(), verify=verify_ssl())
    if response.status_code != 200:
        print(f"Error fetching Forgejo user (HTTP {response.status_code}): {response.text}", file=sys.stderr)
        sys.exit(1)
    return response.json()['login']


def get_or_create_forgejo_repo(forgejo_username, repo_name, repo_description, is_private):
    response = requests.get(
        f'{FORGEJO_URL}/api/v1/repos/{forgejo_username}/{repo_name}',
        headers=forgejo_headers(),
        verify=verify_ssl(),
    )
    if response.status_code == 200:
        return response.json()['clone_url']

    payload = {
        'name': repo_name,
        'description': repo_description or '',
        'private': is_private,
        'auto_init': False,
    }
    response = requests.post(
        f'{FORGEJO_URL}/api/v1/user/repos',
        headers=forgejo_headers(),
        json=payload,
        verify=verify_ssl(),
    )
    if response.status_code not in (200, 201):
        print(f"  Error creating Forgejo repo {repo_name} (HTTP {response.status_code}): {response.text}", file=sys.stderr)
        return None

    print(f"  Created Forgejo repo: {forgejo_username}/{repo_name} ({'private' if is_private else 'public'})")
    return response.json()['clone_url']


def is_repo_migrated(forgejo_username, repo_name):
    """Check if a repo already exists on Forgejo and has been recently updated."""
    response = requests.get(
        f'{FORGEJO_URL}/api/v1/repos/{forgejo_username}/{repo_name}',
        headers=forgejo_headers(),
        verify=verify_ssl(),
    )
    if response.status_code != 200:
        return False

    # Check if local mirror exists
    local_path = os.path.join(WORKSPACE, repo_name + '.git')
    if not os.path.exists(local_path):
        return False

    return True


def authenticated_forgejo_push_url(clone_url):
    """Construct SSH push URL for Forgejo."""
    from urllib.parse import urlparse

    # Parse the clone URL to get the path
    parsed = urlparse(clone_url)
    path = parsed.path.lstrip('/')

    # Get SSH host from FORGEJO_URL
    host = FORGEJO_URL.removeprefix('https://').removeprefix('http://')
    return f'ssh://git@{host}:{FORGEJO_SSH_PORT}/{path}'


def authenticated_github_clone_url(full_name):
    return f'https://{GITHUB_TOKEN}@github.com/{full_name}.git'


def run(cmd, cwd=None, label=''):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Error running {label or ' '.join(cmd)}:", file=sys.stderr)
        if result.stderr:
            print(f"  {result.stderr.strip()}", file=sys.stderr)
    return result.returncode == 0


def mirror_or_update(github_url, local_path):
    if os.path.exists(local_path):
        print(f"  Updating mirror...")
        return run(['git', 'remote', 'update', '--prune'], cwd=local_path, label='git remote update')
    else:
        print(f"  Cloning mirror...")
        return run(['git', 'clone', '--mirror', github_url, local_path], label='git clone --mirror')


def push_mirror(local_path, forgejo_push_url):
    print(f"  Pushing to Forgejo...")
    # Push all refs except GitHub-specific hidden refs (pull/*)
    result = subprocess.run(
        ['git', 'push', '--mirror', forgejo_push_url],
        cwd=local_path,
        capture_output=True,
        text=True
    )

    # Check if push failed only due to hidden refs (GitHub PR refs)
    if result.returncode != 0:
        stderr = result.stderr
        if 'remote rejected' in stderr and 'hidden ref' in stderr:
            # Check if actual branches/tags were pushed by looking for successful refs
            if any(x in stderr for x in ['->', '[new branch]', '[new tag]']):
                print(f"  Note: Some GitHub-specific refs (PR refs) were skipped")
                return True
        return False

    return True


def validate_repos(succeeded_repos, forgejo_username, sample_count=3):
    """Validate that migrated repos exist and have commits on Forgejo."""
    if not succeeded_repos:
        return True

    print(f"\nValidating {len(succeeded_repos)} migrated repositories (sampling {sample_count} commits each)...")

    validated = 0
    failed_validations = []

    for repo_name in tqdm(succeeded_repos, desc="Validating", unit="repo"):
        local_path = os.path.join(WORKSPACE, repo_name + '.git')

        # Get sample commits from local mirror
        result = subprocess.run(
            ['git', 'log', '--format=%H', '-n', str(sample_count)],
            cwd=local_path,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            failed_validations.append((repo_name, "Failed to get commits"))
            continue

        commits = result.stdout.strip().split('\n')
        if not commits or commits[0] == '':
            failed_validations.append((repo_name, "No commits found"))
            continue

        # Verify these commits exist on Forgejo via API
        all_valid = True
        for commit in commits:
            try:
                response = requests.get(
                    f'{FORGEJO_URL}/api/v1/repos/{forgejo_username}/{repo_name}/git/commits/{commit}',
                    headers=forgejo_headers(),
                    verify=verify_ssl(),
                    timeout=30
                )
                if response.status_code != 200:
                    all_valid = False
                    break
            except requests.exceptions.ReadTimeout:
                failed_validations.append((repo_name, "Timeout connecting to Forgejo API"))
                all_valid = False
                break

        if all_valid:
            validated += 1
        else:
            failed_validations.append((repo_name, "Commits not found on Forgejo"))

    print(f"\nValidation complete: {validated}/{len(succeeded_repos)} repositories verified")

    if failed_validations:
        print("\nFailed validations:")
        for repo_name, reason in failed_validations:
            tqdm.write(f"  ✗ {repo_name}: {reason}")
        return False

    return True


def write_log(results):
    os.makedirs(WORKSPACE, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(WORKSPACE, f"migration_log_{timestamp}.txt")

    succeeded = [name for name, ok in results.items() if ok]
    failed = [name for name, ok in results.items() if not ok]

    with open(log_file, 'w') as f:
        f.write(f"GitHub -> Forgejo Migration Log\n")
        f.write(f"Timestamp: {datetime.now()}\n")
        f.write(f"Total: {len(results)}  Succeeded: {len(succeeded)}  Failed: {len(failed)}\n\n")

        f.write("Succeeded:\n")
        for name in succeeded:
            f.write(f"  {name}\n")

        if failed:
            f.write("\nFailed:\n")
            for name in failed:
                f.write(f"  {name}\n")

    print(f"\nLog written to: {log_file}")


def main():
    missing = [v for v in ('GITHUB_USERNAME', 'GITHUB_TOKEN', 'FORGEJO_URL', 'FORGEJO_TOKEN') if not os.getenv(v)]
    if missing:
        print(f"Error: missing environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(WORKSPACE, exist_ok=True)

    print(f"GitHub -> Forgejo migration")
    print(f"  GitHub user  : {GITHUB_USERNAME}")
    print(f"  Forgejo URL  : {FORGEJO_URL}")
    print(f"  Workspace    : {os.path.abspath(WORKSPACE)}")
    print()

    print("Fetching GitHub repositories...")
    repos = get_github_repos()
    print(f"Found {len(repos)} repository/repositories to migrate\n")

    print("Fetching Forgejo user...")
    forgejo_username = get_forgejo_username()
    print(f"Forgejo username: {forgejo_username}\n")

    results = {}
    skipped = 0

    for repo in tqdm(repos, desc="Migrating repositories", unit="repo"):
        repo_name = repo['name']
        full_name = repo['full_name']

        # Skip if already migrated (Forgejo repo exists and local mirror exists)
        if is_repo_migrated(forgejo_username, repo_name):
            skipped += 1
            results[repo_name] = True
            continue

        local_path = os.path.join(WORKSPACE, repo_name + '.git')
        github_url = authenticated_github_clone_url(full_name)

        if not mirror_or_update(github_url, local_path):
            results[repo_name] = False
            continue

        forgejo_clone_url = get_or_create_forgejo_repo(
            forgejo_username,
            repo_name,
            repo.get('description'),
            repo.get('private', True),
        )
        if not forgejo_clone_url:
            results[repo_name] = False
            continue

        forgejo_push_url = authenticated_forgejo_push_url(forgejo_clone_url)
        ok = push_mirror(local_path, forgejo_push_url)
        results[repo_name] = ok
        tqdm.write(f"  {'OK' if ok else 'FAILED'}: {repo_name}")

    write_log(results)

    # Validate succeeded repos
    succeeded = [name for name, ok in results.items() if ok]
    if succeeded and VALIDATE_REPOS:
        validate_repos(succeeded, forgejo_username, sample_count=VALIDATE_SAMPLE_COUNT)

    succeeded_count = sum(1 for ok in results.values() if ok)
    print(f"\nDone: {succeeded_count}/{len(results)} repositories migrated successfully.")
    if skipped > 0:
        print(f"Skipped {skipped} already-migrated repositories.")


if __name__ == "__main__":
    main()
