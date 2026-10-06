import os, re, json, time, html, hashlib
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE = "https://explorer.imd.fun"
JOBS_URL = BASE + "/"
CONTRACTS_URL = BASE + "/published?type=contracts"
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()
CHECK_INTERVAL = max(30, int(os.getenv("CHECK_INTERVAL", "60")))
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
MAX_ITEMS = 30

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 IMD-Telegram-Monitor/1.0",
    "Accept": "text/html,application/xhtml+xml"
})

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"jobs": [], "contracts": [], "initialized": False, "telegram_offset": 0, "chat_id": CHAT_ID}

def save_state(st):
    STATE_FILE.write_text(json.dumps(st, indent=2))

def tg(method, payload=None):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")
    r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload or {}, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(str(data))
    return data["result"]

def send(chat_id, text):
    if not chat_id: return
    tg("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    })

def clean(txt):
    return re.sub(r"\s+", " ", txt or "").strip()

def fetch(url):
    r = session.get(url, timeout=25)
    r.raise_for_status()
    return r.text

def nearest_card(a):
    # IMD currently renders each result as a compact block. Walk upward until
    # we get enough text for a useful Telegram notification, but not the page.
    node = a
    for _ in range(7):
        if not getattr(node, "parent", None): break
        node = node.parent
        txt = clean(node.get_text(" ", strip=True))
        if 20 <= len(txt) <= 900:
            links = node.find_all("a", href=True)
            if len(links) >= 1:
                return node
    return a.parent

def extract_items(page_html, kind):
    soup = BeautifulSoup(page_html, "html.parser")
    items, seen = [], set()

    # Detail links are the most stable identifiers visible on both IMD pages.
    anchors = [a for a in soup.find_all("a", href=True)
               if clean(a.get_text(" ", strip=True)).lower() == "details"]

    for a in anchors:
        href = urljoin(BASE, a["href"])
        if href in seen: continue
        seen.add(href)
        card = nearest_card(a)
        text = clean(card.get_text(" ", strip=True))
        text = re.sub(r"\bdetails\b", "", text, flags=re.I).strip()

        # Ignore nav/footer accidents.
        if not text or len(text) < 3: continue

        # Stable key survives relative-time text changes ("3m ago" -> "4m ago").
        key = hashlib.sha256(href.encode()).hexdigest()[:20]
        title = text
        title = re.sub(r"^(created|published)\s+\S+(?:\s+ago)?\s*", "", title, flags=re.I)
        if len(title) > 500:
            title = title[:497] + "..."

        items.append({"key": key, "url": href, "text": title, "kind": kind})
        if len(items) >= MAX_ITEMS:
            break
    return items

def fmt(item):
    icon = "🆕" if item["kind"] == "job" else "🟢"
    label = "NEW IMD JOB" if item["kind"] == "job" else "NEW IMD CONTRACT"
    body = html.escape(item["text"])
    url = html.escape(item["url"], quote=True)
    return f"{icon} <b>{label}</b>\n\n{body}\n\n<a href=\"{url}\">Open in IMD Explorer</a>"

def check_updates(st):
    # Lets the owner simply message /start to the bot to bind the chat.
    try:
        updates = tg("getUpdates", {
            "offset": int(st.get("telegram_offset", 0)),
            "timeout": 0,
            "allowed_updates": ["message"]
        })
        for u in updates:
            st["telegram_offset"] = u["update_id"] + 1
            msg = u.get("message", {})
            chat = msg.get("chat", {})
            text = (msg.get("text") or "").strip()
            if text.startswith("/start") or text.startswith("/chatid"):
                st["chat_id"] = str(chat.get("id"))
                send(st["chat_id"],
                     "✅ <b>IMD Monitor connected</b>\n\n"
                     "I’ll notify this chat about new IMD jobs and published contracts.\n"
                     f"Check interval: {CHECK_INTERVAL}s")
            elif text.startswith("/status"):
                send(str(chat.get("id")),
                     "🟢 <b>IMD Monitor is running</b>\n"
                     f"Jobs tracked: {len(st.get('jobs', []))}\n"
                     f"Contracts tracked: {len(st.get('contracts', []))}\n"
                     f"Interval: {CHECK_INTERVAL}s")
        save_state(st)
    except Exception as e:
        print("Telegram polling error:", e, flush=True)

def monitor_once(st):
    jobs = extract_items(fetch(JOBS_URL), "job")
    contracts = extract_items(fetch(CONTRACTS_URL), "contract")

    current_jobs = [x["key"] for x in jobs]
    current_contracts = [x["key"] for x in contracts]

    if not st.get("initialized"):
        # Seed current items so first launch does not dump old history.
        st["jobs"] = current_jobs
        st["contracts"] = current_contracts
        st["initialized"] = True
        save_state(st)
        if st.get("chat_id"):
            send(st["chat_id"],
                 "👀 <b>IMD Monitor initialized</b>\n\n"
                 "Current Explorer items were saved as the baseline. "
                 "I’ll alert only when something new appears.")
        print("Initialized baseline:", len(jobs), "jobs,", len(contracts), "contracts", flush=True)
        return

    old_jobs = set(st.get("jobs", []))
    old_contracts = set(st.get("contracts", []))

    # Reverse so multiple new items arrive oldest -> newest.
    for item in reversed(jobs):
        if item["key"] not in old_jobs:
            send(st.get("chat_id"), fmt(item))
    for item in reversed(contracts):
        if item["key"] not in old_contracts:
            send(st.get("chat_id"), fmt(item))

    # Keep recent IDs plus old IDs to reduce duplicate risk if page ordering changes.
    st["jobs"] = list(dict.fromkeys(current_jobs + st.get("jobs", [])))[:300]
    st["contracts"] = list(dict.fromkeys(current_contracts + st.get("contracts", [])))[:300]
    save_state(st)

def main():
    if not BOT_TOKEN:
        raise SystemExit("Set BOT_TOKEN first.")
    st = load_state()
    print("IMD Telegram Monitor started", flush=True)
    while True:
        check_updates(st)
        try:
            monitor_once(st)
        except Exception as e:
            print("Monitor error:", repr(e), flush=True)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
