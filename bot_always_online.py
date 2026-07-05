import datetime
import hashlib
import json
import os
import re
import time
from collections import defaultdict
from threading import Lock, Thread

import pytz
import requests
from flask import Flask

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("TELEGRAM_TOKEN environment variable not set!")

RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY", "")
JSONBIN_BIN_ID = os.environ.get("JSONBIN_BIN_ID", "")

BOT_PASSWORD = "password"
BUSINESS_ID = "e5779c5a-328d-448d-bad5-b69f7370db03"
STAFF_ID = "339008"
SERVICES = {
    "\U0001F466 Short hair (1 hour)": "1802687:SV",
    "\U0001F467 Long hair (1.5 hours)": "1802702:SV",
}
BOOKING_URL = "https://bookings.gettimely.com/hairbytaras/book"

MELBOURNE_TZ = pytz.timezone("Australia/Melbourne")
CHECK_INTERVAL = 120       # seconds between automatic checks
AUTO_CHECK_DAYS = 14       # window monitored automatically
MANUAL_CHECK_DAYS = 90     # window for "Check Now"

# --- STATE ---
state_lock = Lock()        # protects the sets and hash below
check_lock = Lock()        # only one slot check may run at a time

active_chat_ids = set()
authenticated_users = set()
last_slots_hash = None     # hash of slots in the AUTO window only
last_check_string = "Not checked yet"
last_slot_found_time = None


def log(message):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def melbourne_now():
    return datetime.datetime.now(MELBOURNE_TZ)


# --- PERSISTENT STORAGE (JSONBin.io) ---
def save_state():
    with state_lock:
        data = {
            "active_chat_ids": list(active_chat_ids),
            "authenticated_users": list(authenticated_users),
            "last_slots_hash": last_slots_hash,
            "updated_at": datetime.datetime.now().isoformat(),
        }
    if not (JSONBIN_API_KEY and JSONBIN_BIN_ID):
        log("JSONBin not configured; state will be lost on restart")
        return
    try:
        r = requests.put(
            f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}",
            json=data,
            headers={"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"},
            timeout=10,
        )
        if r.status_code != 200:
            log(f"JSONBin save failed: {r.status_code}")
    except Exception as e:
        log(f"JSONBin save error: {e}")


def load_state():
    global active_chat_ids, authenticated_users, last_slots_hash
    if not (JSONBIN_API_KEY and JSONBIN_BIN_ID):
        return
    try:
        r = requests.get(
            f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest",
            headers={"X-Master-Key": JSONBIN_API_KEY},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("record", {})
            with state_lock:
                active_chat_ids = set(data.get("active_chat_ids", []))
                authenticated_users = set(data.get("authenticated_users", []))
                last_slots_hash = data.get("last_slots_hash")
            log(f"Loaded {len(active_chat_ids)} users from JSONBin")
    except Exception as e:
        log(f"JSONBin load error: {e}")


# --- TELEGRAM ---
KEYBOARD = {
    "keyboard": [
        [{"text": "\U0001F4CA Status"}, {"text": "\U0001F50D Check Now"}],
        [{"text": "\U0001F515 Stop Notifications"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


def send_message(chat_id, text, retries=3):
    """Always sends a NEW message, so Telegram delivers a push notification.
    Returns the new message's id, or None on failure."""
    for attempt in range(retries):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "reply_markup": KEYBOARD,
                },
                timeout=10,
            )
            result = r.json()
            if result.get("ok"):
                return result["result"]["message_id"]
            error = result.get("description", "unknown error")
            log(f"Send to {chat_id} failed: {error}")
            if "blocked" in error.lower() or "deactivated" in error.lower():
                with state_lock:
                    active_chat_ids.discard(chat_id)
                    authenticated_users.discard(chat_id)
                save_state()
                return None
        except Exception as e:
            log(f"Send error: {e}")
        time.sleep(2 ** attempt)
    return None


def delete_message(chat_id, message_id):
    """Best-effort deletion; ignores errors (e.g. message already gone)."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
            timeout=10,
        )
    except Exception as e:
        log(f"Delete error: {e}")


def send_temp_message(chat_id, text, delete_after=45):
    """Send a message that auto-deletes after `delete_after` seconds, to keep
    the chat uncluttered. Used for status and other throwaway replies."""
    msg_id = send_message(chat_id, text)
    if msg_id:
        def _expire():
            time.sleep(delete_after)
            delete_message(chat_id, msg_id)
        Thread(target=_expire, daemon=True).start()
    return msg_id


def broadcast(text):
    with state_lock:
        targets = [c for c in active_chat_ids if c in authenticated_users]
    for chat_id in targets:
        send_message(chat_id, text)
        time.sleep(0.1)
    log(f"Broadcast sent to {len(targets)} users")


# --- BOOKING SITE ---
def new_booking_session():
    """A fresh session per check, so concurrent checks can't corrupt each other."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
        "Accept": "text/html, */*; q=0.01",
        "Accept-Language": "en-GB,en-AU;q=0.9,en;q=0.8",
        "Origin": "https://book.gettimely.com",
        "Referer": f"https://book.gettimely.com/Booking/Service?obg={BUSINESS_ID}",
        "X-Requested-With": "XMLHttpRequest",
    })
    return s


def set_service(s, service_id):
    payload = {
        "OnlineBookingMultiServiceEnabled": "True",
        "LocationId": "0",
        "BookableTimeSlotItemIds": service_id,
        f"ServiceStaffIds[{service_id}]": STAFF_ID,
    }
    for attempt in range(3):
        try:
            r = s.post(
                f"https://book.gettimely.com/Booking/Service?obg={BUSINESS_ID}",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            if r.status_code == 200:
                return True
            log(f"set_service returned HTTP {r.status_code}")
        except Exception as e:
            log(f"set_service error: {e}")
        time.sleep(2 ** attempt)
    return False


def get_open_dates(s, year, month):
    try:
        r = s.get(
            "https://book.gettimely.com/Booking/GetOpenDates",
            params={"obg": BUSINESS_ID, "month": month, "year": year,
                    "staffId": "-1", "tzId": "57"},
            timeout=15,
        )
        if r.status_code != 200:
            log(f"GetOpenDates HTTP {r.status_code} for {month}/{year}")
            return []
        data = r.json()
        return [item["day"] for item in data.get("openDates", []) if "day" in item]
    except json.JSONDecodeError:
        log(f"GetOpenDates returned non-JSON for {month}/{year} "
            "(site changed or bot blocked?)")
    except Exception as e:
        log(f"GetOpenDates error for {month}/{year}: {e}")
    return []


def time_to_minutes(t):
    match = re.match(r"(\d{1,2}):(\d{2})(AM|PM)", t)
    if not match:
        return 0
    hours, minutes, period = int(match.group(1)), int(match.group(2)), match.group(3)
    if period == "PM" and hours != 12:
        hours += 12
    elif period == "AM" and hours == 12:
        hours = 0
    return hours * 60 + minutes


def get_first_time(s, date_str):
    """Earliest time on a date, '' if the page had no recognisable times,
    or None if the request itself failed."""
    try:
        r = s.get(
            "https://book.gettimely.com/booking/gettimeslots/",
            params={"obg": BUSINESS_ID, "dateSelected": date_str,
                    "staffId": "-1", "tzName": "", "tzId": "57"},
            timeout=15,
        )
        if "session-timeout" in r.url.lower() or "Session timeout" in r.text:
            log(f"Session expired while fetching times for {date_str}")
            return None
        times = re.findall(r"\d{1,2}:\d{2}\s*(?:am|pm)", r.text, re.IGNORECASE)
        if not times:
            return ""
        normalised = {t.replace(" ", "").upper() for t in times}
        return min(normalised, key=time_to_minutes)
    except Exception as e:
        log(f"gettimeslots error for {date_str}: {e}")
        return None


def months_in_range(start, end):
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return months


def check_slots(days):
    """Return {service_name: [(date, first_time), ...]} for the next `days` days."""
    with check_lock:
        today = melbourne_now().date()
        cutoff = today + datetime.timedelta(days=days)
        results = defaultdict(list)
        for service_name, service_id in SERVICES.items():
            log(f"Checking {service_name}...")
            s = new_booking_session()
            if not set_service(s, service_id):
                log(f"Could not select {service_name}, skipping")
                continue
            for year, month in months_in_range(today, cutoff):
                for date_str in get_open_dates(s, year, month):
                    try:
                        d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if d < today or d > cutoff or (d.year, d.month) != (year, month):
                        continue
                    first_time = get_first_time(s, date_str)
                    if first_time is None:
                        continue  # request failed, don't invent a slot
                    if first_time == "":
                        # Date is open but no time parsed: count it anyway, so a
                        # change in Timely's page format can't silence the bot.
                        log(f"Open date {date_str} but no time parsed "
                            "(site format changed?)")
                        first_time = "time unknown"
                    results[service_name].append((d, first_time))
                    time.sleep(0.3)
                time.sleep(0.5)
        return results


def hash_slots(results):
    if not results:
        return None  # "no slots" hashes to None, so a returning slot re-alerts
    lines = []
    for name in sorted(results):
        for d, t in sorted(results[name]):
            lines.append(f"{name}|{d}|{t}")
    return hashlib.md5("|".join(lines).encode()).hexdigest()


def format_results(results, extra_note=None):
    msg = "\U0001F389 <b>Slots found!</b>\n"
    for name, slots in results.items():
        if slots:
            msg += f"\n<b>{name}</b>\n"
            for d, t in sorted(slots):
                msg += f"\u2022 {d.day} {d.strftime('%B')}: {t}\n"
    if extra_note:
        msg += f"\n{extra_note}\n"
    msg += f"\n<a href='{BOOKING_URL}'>\U0001F4C5 Book now</a>"
    return msg


def time_since_last_slot():
    if last_slot_found_time is None:
        return "No slots found yet"
    seconds = int((melbourne_now() - last_slot_found_time).total_seconds())
    for unit_seconds, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= unit_seconds:
            n = seconds // unit_seconds
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return f"{seconds} seconds ago"


# --- COMMAND HANDLERS ---
def handle_status(chat_id):
    send_temp_message(chat_id, f"""\U0001F4CA <b>Bot status</b>
\U0001F916 Status: <b>Running</b>
\U0001F550 Last check: <b>{last_check_string}</b>
\U0001F4C5 Last slot: <b>{time_since_last_slot()}</b>
\U0001F50D Monitoring: next {AUTO_CHECK_DAYS} days, every {CHECK_INTERVAL // 60} minutes
\U0001F465 Active users: {len(active_chat_ids)}""")


NEAR_TERM_DAYS = 30  # boundary between the detailed list and the one-line note


def split_by_horizon(results, near_days):
    today = melbourne_now().date()
    cutoff = today + datetime.timedelta(days=near_days)
    near, far = defaultdict(list), defaultdict(list)
    for name, slots in results.items():
        for d, t in slots:
            (near if d <= cutoff else far)[name].append((d, t))
    return near, far


def handle_check_now(chat_id):
    # Transient progress message; deleted once the result is ready.
    checking_id = send_message(
        chat_id, f"\U0001F50D <b>Checking the next {MANUAL_CHECK_DAYS} days...</b>")
    # A manual check never touches last_slots_hash, so it can't
    # suppress or duplicate the automatic notifications.
    results = check_slots(MANUAL_CHECK_DAYS)
    near, far = split_by_horizon(results, NEAR_TERM_DAYS)

    far_note = None
    if far:
        far_note = (f"There are also slots available between "
                    f"{NEAR_TERM_DAYS} and {MANUAL_CHECK_DAYS} days from now.")

    if near:
        # far_note (no icon) is placed just above the Book now link.
        text = format_results(near, extra_note=far_note)
    else:
        text = (f"\u274C <b>No slots in the next {NEAR_TERM_DAYS} days</b>\n\n"
                "I'll notify you automatically when something opens up.")
        if far_note:
            text += f"\n\n{far_note}\n"
            text += f"\n<a href='{BOOKING_URL}'>\U0001F4C5 Book now</a>"

    send_message(chat_id, text)
    if checking_id:
        delete_message(chat_id, checking_id)


def handle_stop(chat_id):
    with state_lock:
        active_chat_ids.discard(chat_id)
    save_state()
    send_message(chat_id, "\U0001F515 <b>Unsubscribed</b>\n\nSend any message to re-subscribe.")


def handle_resubscribe(chat_id):
    with state_lock:
        active_chat_ids.add(chat_id)
    save_state()
    send_message(chat_id, "\U0001F514 <b>Re-subscribed!</b> "
                          "You'll be notified when slots open up.")


# --- BACKGROUND LOOPS ---
def auto_check_loop():
    global last_slots_hash, last_slot_found_time, last_check_string
    log("Starting automatic check loop...")
    while True:
        try:
            results = check_slots(AUTO_CHECK_DAYS)
            last_check_string = melbourne_now().strftime("%I:%M %p")
            new_hash = hash_slots(results)

            if results:
                last_slot_found_time = melbourne_now()

            if new_hash != last_slots_hash:
                with state_lock:
                    last_slots_hash = new_hash
                save_state()
                if results:
                    log("Slots changed, notifying users")
                    broadcast(format_results(results))
                else:
                    log("Slots disappeared; hash reset")
            elif results:
                log("Slots exist but unchanged")
            else:
                log("No slots")
        except Exception as e:
            log(f"Error in check loop: {e}")
        time.sleep(CHECK_INTERVAL)


def self_ping_loop():
    if not RENDER_EXTERNAL_URL:
        log("RENDER_EXTERNAL_URL not set; self-ping disabled")
        return
    url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/ping"
    log(f"Self-ping enabled: {url} every 10 minutes")
    while True:
        time.sleep(600)
        try:
            requests.get(url, timeout=10)
        except Exception as e:
            log(f"Self-ping failed: {e}")


# --- FLASK (keep-alive) ---
app = Flask(__name__)


@app.route("/")
def home():
    return (f"<h1>Hair Appointment Bot</h1>"
            f"<p>Status: \u2705 Running</p>"
            f"<p>Active users: {len(active_chat_ids)}</p>"
            f"<p>Last check: {last_check_string}</p>"
            f"<p>Last slot: {time_since_last_slot()}</p>")


@app.route("/ping")
@app.route("/health")
def ping():
    return {"status": "alive", "last_check": last_check_string}, 200


def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    log(f"Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)


# --- MAIN TELEGRAM LOOP ---
def telegram_loop():
    log("Starting Telegram bot...")
    offset = None
    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"timeout": 30, "offset": offset,
                        "allowed_updates": json.dumps(["message"])},
                timeout=40,
            )
            data = r.json()
            if not data.get("ok"):
                log(f"getUpdates error: {data}")
                time.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg:
                    continue
                chat_id = msg["chat"]["id"]
                text = msg.get("text", "").strip()
                log(f"Message from {chat_id}: '{text}'")

                # Remove the user's incoming message so button taps, commands
                # and the typed password don't pile up in the chat.
                delete_message(chat_id, msg["message_id"])

                if chat_id not in authenticated_users:
                    if text == BOT_PASSWORD:
                        with state_lock:
                            authenticated_users.add(chat_id)
                            active_chat_ids.add(chat_id)
                        save_state()
                        send_message(chat_id, "\u2705 <b>Welcome!</b>\n\n"
                                              "I check for appointments every 2 minutes "
                                              "and notify you when new slots open up.")
                    else:
                        send_message(chat_id, "\U0001F510 This bot is private. "
                                              "Please enter the password:")
                    continue

                if text == "\U0001F515 Stop Notifications":
                    handle_stop(chat_id)
                elif chat_id not in active_chat_ids:
                    handle_resubscribe(chat_id)
                elif text == "\U0001F50D Check Now":
                    # Run in a thread so a slow check doesn't block the bot
                    Thread(target=handle_check_now, args=(chat_id,), daemon=True).start()
                else:
                    handle_status(chat_id)
        except requests.exceptions.Timeout:
            pass  # normal for long polling
        except Exception as e:
            log(f"Telegram loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    log("Hair Appointment Bot starting...")
    load_state()
    Thread(target=run_http_server, daemon=True).start()
    Thread(target=self_ping_loop, daemon=True).start()
    Thread(target=auto_check_loop, daemon=True).start()
    telegram_loop()
