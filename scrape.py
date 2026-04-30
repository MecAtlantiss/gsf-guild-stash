"""
PoE Guild Stash Unique Showcase Scraper - Persistent Monitor
=============================================================
Scrapes the guild stash showcase every 30 seconds.

Each run saves a timestamped snapshot CSV to ./snapshots/
A master CSV tracks all uniques ever seen, with first-seen timestamps.

Special handling: "Precursor's Emblem" items are renamed based on which
charge types appear in their stats:
  Frenzy    -> G (green)
  Endurance -> R (red)
  Power     -> B (blue)
Combinations are sorted R > G > B, e.g. "Precursor RG", "Precursor RGB"

SETUP:
    pip install requests beautifulsoup4
    Ensure config.py is in the same folder with POESESSID = "your_value"
    Then run: python scrape_guild_stash.py
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import os
import re
import json
from datetime import datetime
import config

POESESSID = config.POESESSID

if not POESESSID:
    raise SystemExit("ERROR: POESESSID is empty in config.py.")

BASE_URL     = "https://www.pathofexile.com/guild/view-stash/995704/c63aa081/{}"
NUM_TABS     = 23
INTERVAL     = 30  # seconds between runs

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_DIR = os.path.join(SCRIPT_DIR, "snapshots")
MASTER_PATH  = os.path.join(SCRIPT_DIR, "guild_stash_master.csv")

os.makedirs(SNAPSHOT_DIR, exist_ok=True)

SESSION = requests.Session()
SESSION.cookies.set("POESESSID", POESESSID, domain="www.pathofexile.com")
SESSION.headers.update({
    "User-Agent":      "GuildStashScraper/1.0 (personal use)",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer":         "https://www.pathofexile.com/",
})


# ── Known variant sets (used for pigeonhole assignment) ─────
PRECURSOR_VARIANTS = [
    "Precursor R",
    "Precursor G",
    "Precursor B",
    "Precursor RG",
    "Precursor RB",
    "Precursor GB",
    "Precursor RGB",
]

GRAND_SPECTRUM_VARIANTS = [
    "Grand Spectrum Frenzy",
    "Grand Spectrum Endurance",
    "Grand Spectrum Power",
    "Grand Spectrum Life",
    "Grand Spectrum Resistances",
    "Grand Spectrum Crit Chance",
    "Grand Spectrum Elemental Damage",
    "Grand Spectrum Minions",
    "Grand Spectrum Avoid Ailments",
]


# ── Precursor's Emblem handling ───────────────────────────

def precursor_label(item_json):
    """
    Given a parsed item JSON dict, return a label like "Precursor RG".
    Scans all mod fields for Endurance / Frenzy / Power keywords.
    Order is always R -> G -> B.
    Falls back to "Precursor's Emblem" if nothing is detected.
    """
    mod_fields = [
        "implicitMods", "explicitMods", "utilityMods",
        "enchantMods", "craftedMods", "fracturedMods",
    ]
    all_text = " ".join(
        mod
        for field in mod_fields
        for mod in item_json.get(field, [])
        if isinstance(mod, str)
    )

    has_r = "Endurance" in all_text
    has_g = "Frenzy"    in all_text
    has_b = "Power"     in all_text

    if not any([has_r, has_g, has_b]):
        print(f"    WARNING: Could not detect charge type for Precursor's Emblem. Mods: {all_text!r}")
        return "Precursor's Emblem"

    label = "Precursor "
    if has_r: label += "R"
    if has_g: label += "G"
    if has_b: label += "B"
    return label


def grand_spectrum_label(item_json):
    """
    Given a parsed item JSON dict, return the correct Grand Spectrum label.
    Looks for Frenzy / Endurance / Power / Life keywords in mods.
    Falls back to "Grand Spectrum" if nothing is detected.
    """
    mod_fields = [
        "implicitMods", "explicitMods", "utilityMods",
        "enchantMods", "craftedMods", "fracturedMods",
    ]
    all_text = " ".join(
        mod
        for field in mod_fields
        for mod in item_json.get(field, [])
        if isinstance(mod, str)
    )

    if "Frenzy"                in all_text: return "Grand Spectrum Frenzy"
    if "Endurance"             in all_text: return "Grand Spectrum Endurance"
    if "Power"                 in all_text: return "Grand Spectrum Power"
    if "Life"                  in all_text: return "Grand Spectrum Life"
    if "Elemental Resistances" in all_text: return "Grand Spectrum Resistances"
    if "Critical Strike Chance" in all_text: return "Grand Spectrum Crit Chance"
    if "Elemental Damage"      in all_text: return "Grand Spectrum Elemental Damage"
    if "Minions"               in all_text: return "Grand Spectrum Minions"
    if "Avoid Elemental"       in all_text: return "Grand Spectrum Avoid Ailments"

    print(f"    WARNING: Could not detect type for Grand Spectrum. Mods: {all_text!r}")
    return "Grand Spectrum"


def extract_grand_spectrum_queue(page_html):
    """
    Parse the DeferredItemRenderer JSON and return an ordered list of
    item dicts for every Grand Spectrum found, in DOM order.
    """
    match = re.search(
        r'\(new R\((\[\[.*?\]\])\)\)\.run\(\)',
        page_html,
        re.DOTALL
    )
    if not match:
        return []

    try:
        items_array = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    return [
        entry[1]
        for entry in items_array
        if len(entry) >= 2
        and isinstance(entry[1], dict)
        and entry[1].get("name") == "Grand Spectrum"
    ]


def extract_precursor_queue(page_html):
    """
    Parse the DeferredItemRenderer JSON from the page and return an ordered
    list of parsed item dicts for every Precursor's Emblem found, in the
    order they appear in the JSON (which matches DOM order).

    The JS blob looks like:
        (new R([[0, {item}, {opts}], [1, {item}, {opts}], ...])).run();
    """
    match = re.search(
        r'\(new R\((\[\[.*?\]\])\)\)\.run\(\)',
        page_html,
        re.DOTALL
    )
    if not match:
        # Normal if the tab has no owned items — no JSON is embedded in that case
        return []

    try:
        items_array = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"    WARNING: Failed to parse item JSON: {e}")
        return []

    # Pull out only the Precursor's Emblem entries, preserving order
    return [
        entry[1]
        for entry in items_array
        if len(entry) >= 2
        and isinstance(entry[1], dict)
        and entry[1].get("name") == "Precursor's Emblem"
    ]


# ── Core scraping ─────────────────────────────────────────

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

        # Extract JSON queues for multi-variant items
        precursor_queue      = extract_precursor_queue(resp.text)
        precursor_iter       = iter(precursor_queue)
        grand_spectrum_queue = extract_grand_spectrum_queue(resp.text)
        grand_spectrum_iter  = iter(grand_spectrum_queue)

        # First pass: collect all items on this page, identifying owned
        # variants by their mods and marking unowned ones as placeholders.
        page_precursors     = []  # list of {"name": str|None, "owned": bool}
        page_grand_spectra  = []
        page_others         = []

        for item in soup.select("div.item"):
            name_tag = item.select_one("div.name span")
            if not name_tag:
                continue

            raw_name = name_tag.get_text(strip=True)
            owned    = 0 if "unowned" in item.get("class", []) else 1

            if raw_name in ("Bisco's Collar", "The Ascetic", "Eldritch Knowledge"):
                continue

            if raw_name == "Precursor's Emblem":
                item_json = next(precursor_iter, {})
                if owned:
                    # Owned: we can read the mods to identify the variant
                    display_name = precursor_label(item_json)
                else:
                    # Unowned: placeholder — will assign by elimination below
                    display_name = None
                page_precursors.append({"name": display_name, "owned": owned})

            elif raw_name == "Grand Spectrum":
                item_json = next(grand_spectrum_iter, {})
                if owned:
                    display_name = grand_spectrum_label(item_json)
                else:
                    display_name = None
                page_grand_spectra.append({"name": display_name, "owned": owned})

            else:
                page_others.append({"name": raw_name, "owned": owned})

        # Second pass: assign unowned placeholders by elimination.
        # The known variants that were identified as owned are removed from
        # the pool; remaining variants are assigned in order to the unowned slots.
        def assign_unowned(entries, all_variants):
            owned_names = {e["name"] for e in entries if e["owned"] and e["name"]}
            remaining   = [v for v in all_variants if v not in owned_names]
            remaining_iter = iter(remaining)
            assigned = []
            for e in entries:
                if e["name"] is not None:
                    assigned.append(e)
                else:
                    fallback = next(remaining_iter, "Unknown")
                    assigned.append({"name": fallback, "owned": e["owned"]})
            return assigned

        page_precursors    = assign_unowned(page_precursors,    PRECURSOR_VARIANTS)
        page_grand_spectra = assign_unowned(page_grand_spectra, GRAND_SPECTRUM_VARIANTS)

        # Combine all items and append to results
        for entry in page_others + page_precursors + page_grand_spectra:
            results.append({
                "Unique Name": entry["name"],
                "Have":        entry["owned"],
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