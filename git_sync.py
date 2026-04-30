"""
git_sync.py — Auto-push CSVs to GitHub
=======================================
Watches guild_stash_master.csv and important_uniques.csv for changes
and pushes to GitHub only when a file actually changes (MD5 comparison).

Run this in a second terminal alongside scrape_guild_stash.py:
    python git_sync.py

REQUIREMENTS:
- Git must be installed and on your PATH
- This script must live in the root of your git repo
- Your repo must already have a remote named "origin" pointing to GitHub
- You must have push access (SSH key or stored credentials)
"""

import hashlib
import subprocess
import time
import os
from datetime import datetime

SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
MASTER_FILE    = os.path.join(SCRIPT_DIR, "guild_stash_master.csv")
IMPORTANT_FILE = os.path.join(SCRIPT_DIR, "important_uniques.csv")
WATCHED_FILES  = [MASTER_FILE, IMPORTANT_FILE]
CHECK_INTERVAL = 15  # seconds between checks


def file_hash(path):
    """Return MD5 hash of file, or None if it doesn't exist."""
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def git(*args):
    """Run a git command in the repo directory."""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def get_current_branch():
    """Return the current git branch name."""
    code, out, err = git("rev-parse", "--abbrev-ref", "HEAD")
    return out if code == 0 else "master"


def has_upstream():
    """Return True if the current branch already has a remote tracking branch."""
    code, out, err = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return code == 0


def push_changes(changed_files):
    """Stage, commit, and push the changed files."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    names     = [os.path.basename(f) for f in changed_files]

    for f in changed_files:
        code, out, err = git("add", f)
        if code != 0:
            print(f"  [git add] ERROR on {os.path.basename(f)}: {err}")
            return False

    msg = f"Update {', '.join(names)} -- {timestamp}"
    code, out, err = git("commit", "-m", msg)
    if code != 0:
        if "nothing to commit" in out or "nothing to commit" in err:
            print(f"  [git commit] Nothing new to commit.")
            return True
        print(f"  [git commit] ERROR: {err}")
        return False

    print(f"  [git commit] {out.splitlines()[0] if out else 'committed'}")

    # Set upstream automatically if this branch hasn't been pushed before
    if has_upstream():
        code, out, err = git("push")
    else:
        branch = get_current_branch()
        print(f"  [git push] No upstream set — pushing with --set-upstream origin {branch}")
        code, out, err = git("push", "--set-upstream", "origin", branch)

    if code != 0:
        print(f"  [git push] ERROR: {err}")
        return False

    print(f"  [git push] Pushed successfully at {timestamp}")
    return True


def main():
    print("=" * 55)
    print("  PoE Guild Stash — Git Sync")
    print(f"  Watching:")
    for f in WATCHED_FILES:
        print(f"    {f}")
    print(f"  Checking every {CHECK_INTERVAL}s  |  Ctrl+C to stop")
    print("=" * 55)

    hashes = {f: file_hash(f) for f in WATCHED_FILES}

    for f, h in hashes.items():
        name = os.path.basename(f)
        if h:
            print(f"  {name}: found (hash {h[:8]}...)")
        else:
            print(f"  {name}: not found yet, will watch for it.")

    while True:
        time.sleep(CHECK_INTERVAL)
        now     = datetime.now().strftime("%H:%M:%S")
        changed = []

        for f in WATCHED_FILES:
            current = file_hash(f)
            if current is not None and current != hashes[f]:
                changed.append(f)

        if changed:
            names = [os.path.basename(f) for f in changed]
            print(f"\n[{now}] Change detected in: {', '.join(names)} -- pushing...")
            if push_changes(changed):
                for f in changed:
                    hashes[f] = file_hash(f)
        else:
            print(f"[{now}] No changes.")


if __name__ == "__main__":
    main()