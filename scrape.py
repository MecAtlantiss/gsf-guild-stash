import requests
from bs4 import BeautifulSoup
import csv
import time
import os
from datetime import datetime
import config

POESESSID = config.POESESSID

if not POESESSID:
    raise SystemExit("ERROR: POESESSID is empty in config.py.")

BASE_URL    = "https://www.pathofexile.com/guild/view-stash/995704/c63aa081/{}"
NUM_TABS    = 23
INTERVAL    = 30  # seconds between runs

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_DIR  = os.path.join(SCRIPT_DIR, "snapshots")
MASTER_PATH   = os.path.join(SCRIPT_DIR, "guild_stash_master.csv")

os.makedirs(SNAPSHOT_DIR, exist_ok=True)

SESSION = requests.Session()
SESSION.cookies.set("POESESSID", POESESSID, domain="www.pathofexile.com")
SESSION.headers.update({
    "User-Agent":      "GuildStashScraper/1.0 (personal use)",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer":         "https://www.pathofexile.com/",
})


def load_master():
    """Load master CSV into a dict: { unique_name -> {"Ever Seen": 0/1, "First Seen": ""} }"""
    master = {}
    if os.path.exists(MASTER_PATH):
        with open(MASTER_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                master[row["Unique Name"]] = {
                    "Ever Seen":  int(row["Ever Seen"]),
                    "First Seen": row["First Seen"],
                }
    return master


def save_master(master):
    with open(MASTER_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Unique Name", "Ever Seen", "First Seen"])
        writer.writeheader()
        for name, data in sorted(master.items()):
            writer.writerow({"Unique Name": name, **data})


def scrape():
    """Scrape all tabs. Returns list of {"Unique Name": str, "Have": 0/1}."""
    results = []
    for tab in range(1, NUM_TABS + 1):
        try:
            resp = SESSION.get(BASE_URL.format(tab), timeout=15)
            resp.raise_for_status()
        except requests.HTTPError as e:
            print(f"  Tab {tab}: HTTP {e.response.status_code} — skipping.")
            continue
        except Exception as e:
            print(f"  Tab {tab}: {e} — skipping.")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        if "loginForm" in resp.text or (soup.title and "Sign In" in soup.title.get_text()):
            raise SystemExit("ERROR: Session expired. Update POESESSID and restart.")

        for item in soup.select("div.item"):
            name_tag = item.select_one("div.name span")
            if not name_tag:
                continue
            results.append({
                "Unique Name": name_tag.get_text(strip=True),
                "Have":        0 if "unowned" in item.get("class", []) else 1,
            })

        time.sleep(0.5)  # gentle between tabs

    return results


def run_once(run_number):
    now       = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    filestamp = now.strftime("%Y%m%d_%H%M%S")

    print(f"\n[Run #{run_number}] {timestamp} — scraping {NUM_TABS} tabs...")
    results = scrape()

    if not results:
        print("  No data returned, skipping this run.")
        return

    # Save snapshot
    snapshot_path = os.path.join(SNAPSHOT_DIR, f"snapshot_{filestamp}.csv")
    with open(snapshot_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Unique Name", "Have"])
        writer.writeheader()
        writer.writerows(results)

    # Update master
    master = load_master()
    newly_seen = []

    for row in results:
        name = row["Unique Name"]
        if name not in master:
            # New unique encountered for the first time across all runs
            master[name] = {"Ever Seen": 0, "First Seen": ""}

        if row["Have"] == 1 and master[name]["Ever Seen"] == 0:
            master[name]["Ever Seen"]  = 1
            master[name]["First Seen"] = timestamp
            newly_seen.append(name)

    save_master(master)

    owned = sum(r["Have"] for r in results)
    total = len(results)
    print(f"  Snapshot : {os.path.basename(snapshot_path)}")
    print(f"  Items    : {owned}/{total} owned")
    if newly_seen:
        print(f"  NEW this run ({len(newly_seen)}): {', '.join(newly_seen)}")
    else:
        print(f"  No new uniques this run.")


def main():
    print("=" * 55)
    print("  PoE Guild Stash Monitor")
    print(f"  Polling every {INTERVAL}s  |  Ctrl+C to stop")
    print("=" * 55)

    run_number = 1
    while True:
        try:
            run_once(run_number)
        except SystemExit:
            raise
        except Exception as e:
            print(f"  Unexpected error: {e}")

        run_number += 1
        print(f"  Next run in {INTERVAL}s...")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()