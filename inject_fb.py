import sys, json, re, urllib.request, pathlib

FIREBASE_URL = "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app"
HTML_FILE    = pathlib.Path(r"C:\Users\BioCSI\CLAUDE\GridTracker\bist_tracker.html")

# Firebase'den veri cek
url = FIREBASE_URL + "/gridtracker.json"
print(f"Fetching: {url}")
try:
    with urllib.request.urlopen(url, timeout=15) as r:
        raw = r.read().decode('utf-8')
    fb = json.loads(raw)
    print(f"Firebase keys: {list(fb.keys()) if isinstance(fb, dict) else type(fb)}")
    m = None
    if isinstance(fb, dict):
        lu = fb.get('lastUpdated') or fb.get('last_updated')
        if lu: print(f"lastUpdated: {lu}")
except Exception as e:
    print(f"ERROR fetching Firebase: {e}")
    sys.exit(1)

# HTML oku
html = HTML_FILE.read_text(encoding='utf-8')

# Payload JSON
payload_str = json.dumps(fb, ensure_ascii=False, indent=2)

new_block = (
    "                // GRID_DATA_START\n"
    "        window.__GRID_DATA__ = " + payload_str + ";\n"
    "        // GRID_DATA_END"
)

new_html = re.sub(
    r'// GRID_DATA_START.*?// GRID_DATA_END',
    new_block, html, flags=re.DOTALL
)

if new_html == html:
    print("WARNING: GRID_DATA pattern not found in HTML - nothing replaced")
    sys.exit(1)

HTML_FILE.write_text(new_html, encoding='utf-8')
size = HTML_FILE.stat().st_size
lines = new_html.count('\n')
print(f"OK: HTML updated - {lines} lines, {size//1024} KB")

# Dogrulama
check = re.search(r'"lastUpdated"\s*:\s*"([^"]+)"', new_html)
if check:
    print(f"Embedded lastUpdated: {check.group(1)}")
if 'window.__GRID_DATA__ = null' in new_html:
    print("PROBLEM: Still null!")
else:
    print("Data injected successfully.")
