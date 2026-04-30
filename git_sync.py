"""
git_sync.py — Auto-push any changes to GitHub
===============================================
Watches the entire repo for changes (respecting .gitignore) and pushes
to GitHub whenever anything is modified, added, or deleted.

Run this in a second terminal alongside scrape_guild_stash.py:
    python git_sync.py

REQUIREMENTS:
- Git must be installed and on your PATH
- This script must live in the root of your git repo
- Your repo must already have a remote named "origin" pointing to GitHub
- You must have push access (SSH key or stored credentials)
"""

import subprocess
import time
import os
from datetime import datetime

SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
CHECK_INTERVAL = 15  # seconds between checks


def git(*args):
    """Run a git command in the repo directory."""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def get_changed_files():
    """
    Return a list of files that have changes git would care about:
    - Modified or new untracked files not excluded by .gitignore
    - Deleted files
    Uses 'git status --porcelain' which respects .gitignore automatically.
    """
    code, out, err = git("status", "--porcelain")
    if code != 0 or not out:
        return []
    changed = []
    for line in out.splitlines():
        # porcelain format: XY filename (XY are status codes, filename follows)
        filename = line[3:].strip()
        # Handle renames: "old -> new" format
        if " -> " in filename:
            filename = filename.split(" -> ")[-1]
        changed.append(filename)
    return changed


def get_current_branch():
    """Return the current git branch name."""
    code, out, err = git("rev-parse", "--abbrev-ref", "HEAD")
    return out if code == 0 else "master"


def has_upstream():
    """Return True if the current branch already has a remote tracking branch."""
    code, out, err = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return code == 0


def push_changes(changed_files):
    """Stage all changes, commit, and push."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Stage everything git is aware of (respects .gitignore)
    code, out, err = git("add", "-A")
    if code != 0:
        print(f"  [git add] ERROR: {err}")
        return False

    # Summarise what's changing for the commit message
    if len(changed_files) <= 3:
        names = ", ".join(changed_files)
    else:
        names = f"{len(changed_files)} files"

    msg = f"Update {names} -- {timestamp}"
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
        print(f"  [git push] No upstream set -- pushing with --set-upstream origin {branch}")
        code, out, err = git("push", "--set-upstream", "origin", branch)

    if code != 0:
        print(f"  [git push] ERROR: {err}")
        return False

    print(f"  [git push] Pushed successfully at {timestamp}")
    return True


def main():
    print("=" * 55)
    print("  PoE Guild Stash -- Git Sync")
    print(f"  Watching entire repo (respecting .gitignore)")
    print(f"  Repo: {SCRIPT_DIR}")
    print(f"  Checking every {CHECK_INTERVAL}s  |  Ctrl+C to stop")
    print("=" * 55)

    # Show initial status
    initial = get_changed_files()
    if initial:
        print(f"  Pending uncommitted changes: {', '.join(initial)}")
    else:
        print(f"  Repo is clean.")

    while True:
        time.sleep(CHECK_INTERVAL)
        now     = datetime.now().strftime("%H:%M:%S")
        changed = get_changed_files()

        if changed:
            print(f"\n[{now}] Changes detected: {', '.join(changed)} -- pushing...")
            push_changes(changed)
        else:
            print(f"[{now}] No changes.")


if __name__ == "__main__":
    main()
