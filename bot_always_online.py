import requests
import os
import datetime
import time
import re
from collections import defaultdict
import pytz
import random
import json
from threading import Thread, Lock
from flask import Flask
import sys

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not BOT_TOKEN:
    print("ERROR: TELEGRAM_TOKEN environment variable not set!", file=sys.stderr)
    raise Exception("TELEGRAM_TOKEN environment variable not set!")

print(f"Bot token loaded: {BOT_TOKEN[:10]}...")

BOT_PASSWORD = "password"

BUSINESS_ID = "8ab07528-c2a9-463d-a441-3e0aa39a975e"
STAFF_ID = "339008"

SERVICES_TO_CHECK = {
    "👦 Short hair (1 hour)": "1802687:SV",
    "👧 Long hair (1.5 hours)": "1802702:SV"
}

MELBOURNE_TZ = pytz.timezone('Australia/Melbourne')
CHECK_INTERVAL = 120
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW = 60
USERS_FILE = "active_users.json"

# Global variables
active_chat_ids = set()
authenticated_users = set()
last_check_string = "Not checked yet"
last_slot_found_time = None
user_request_times = defaultdict(list)
rate_limit_lock = Lock()
chat_content_message = {}

# --- ONE-LINERS ---
ESOTERIC_LINES = [
    "The stars have aligned. Your split ends have not.",
    "Mercury is in retrograde. Your hair is in disgrace.",
    "The ancient scrolls speak of a prophecy: you need a trim.",
    "Your aura is immaculate. Your hair, however, is chaotic.",
    "The universe whispers: 'Book the appointment.'",
    "Your chakras are balanced. Your layers are not.",
    "The moon is waxing. Your hair should be waning.",
    "I consulted the tarot. The cards said 'scissors.'",
    "The oracle has spoken. It said 'barber. Now.'",
    "Your third eye sees all. It sees that you need a cut.",
    "The cosmos have a message: your ends are split.",
    "Venus governs beauty. She's filed a complaint about your hair.",
    "The tea leaves have settled. They spell 'H-A-I-R-C-U-T.'",
    "Your spirit guide appeared. It was holding clippers.",
    "The pendulum swings toward 'yes, get a trim.'",
    "Saturn returns every 29 years. Your haircut is overdue by 3 months.",
    "The runes are clear: ᚺᚨᛁᚱᚲᚢᛏ (that's 'haircut' in Elder Futhark).",
]

WITTY_LINES = [
    "Your hair called. It wants a divorce.",
    "I've seen better hair on a coconut.",
    "Your hair has more issues than a magazine stand.",
    "That's not a hairstyle, that's a cry for help.",
    "Your hair looks like it lost a fight with a lawnmower.",
    "Is that a hairstyle or a social experiment?",
    "Your hair has given up. Maybe you should too. On the hair.",
    "I'm not saying your hair is bad, but birds are circling it.",
    "Your hair is a 'before' photo that never got an 'after.'",
    "That hair could be used as evidence in court.",
    "Your hair is what happens when you skip the tutorial.",
    "I've seen tidier haystacks.",
    "Your hair looks like it's buffering.",
    "Is your hair a statement? Because it's saying 'help me.'",
    "Your hair has the energy of a forgotten houseplant.",
    "That's not bed head. That's bed, floor, and dumpster head.",
    "Your hair is giving 'I woke up like this' but not in a good way.",
]

CONSULTING_LINES = [
    "Per my last email, your hair requires immediate strategic intervention.",
    "Let's take this offline—your split ends need a private consultation.",
    "I'll need to loop in the scissors on this one.",
    "Your hair's ROI is diminishing. Time to pivot.",
    "Let's circle back when your roots aren't showing.",
    "This is a high-priority follicle situation. Escalate immediately.",
    "Your current style lacks synergy. Consider a trim.",
    "We need to align your hair with Q4 objectives.",
    "I'm seeing some bandwidth issues with your current length.",
    "Your hair is giving 'scope creep.' Rein it in.",
    "The deliverables are clear: you need a cut.",
    "I've done the due diligence. The recommendation is: scissors.",
    "Your hair has exceeded its sprint capacity. Time to groom the backlog.",
    "Let's not boil the ocean—just trim the ends.",
    "Your follicles are misaligned with stakeholder expectations.",
    "We need to rightsize your hair situation.",
    "Your hair's burn rate is unsustainable. Cut costs. Literally.",
    "I'm flagging this as a blocker. The blocker is your hair.",
    "Let's leverage our core competencies here: booking appointments.",
    "Your hair is technical debt. Time to refactor.",
]

HAIRCUT_ADVICE = ESOTERIC_LINES + WITTY_LINES + CONSULTING_LINES
random.shuffle(HAIRCUT_ADVICE)

# Session for appointment checking
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Origin": "https://book.gettimely.com",
    "Referer": f"https://book.gettimely.com/Booking/Service?obg={BUSINESS_ID}",
    "X-Requested-With": "XMLHttpRequest"
})

# --- KEYBOARD DEFINITIONS ---
REPLY_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 Status"}, {"text": "🔍 Check Now"}],
        [{"text": "✂️ Haircut Advice"}],
        [{"text": "🔕 Stop Notifications"}]
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
    "is_persistent": True
}

REMOVE_KEYBOARD = {
    "remove_keyboard": True
}

# --- PERSISTENCE ---
def save_users():
    try:
        data = {
            "active_chat_ids": list(active_chat_ids),
            "authenticated_users": list(authenticated_users)
        }
        with open(USERS_FILE, 'w') as f:
            json.dump(data, f)
        print(f"Saved {len(active_chat_ids)} users to file")
    except Exception as e:
        print(f"Error saving users: {e}")

def load_users():
    global active_chat_ids, authenticated_users
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r') as f:
                data = json.load(f)
                active_chat_ids = set(data.get("active_chat_ids", []))
                authenticated_users = set(data.get("authenticated_users", []))
            print(f"Loaded {len(active_chat_ids)} users from file")
    except Exception as e:
        print(f"Error loading users: {e}")

# --- FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return f"Bot is alive! Active users: {len(active_chat_ids)}"

@app.route('/health')
def health():
    return "OK", 200

def run_http_server():
    try:
        port = int(os.environ.get("PORT", 8080))
        print(f"Starting Flask server on port {port}...")
        app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
    except Exception as e:
        print(f"Error starting Flask server: {e}", file=sys.stderr)
        raise

# --- RATE LIMITING ---
def check_rate_limit(chat_id):
    with rate_limit_lock:
        now = time.time()
        user_request_times[chat_id] = [t for t in user_request_times[chat_id] if now - t < RATE_LIMIT_WINDOW]
        if len(user_request_times[chat_id]) >= RATE_LIMIT_REQUESTS:
            return False
        user_request_times[chat_id].append(now)
        return True

def get_rate_limit_remaining(chat_id):
    with rate_limit_lock:
        now = time.time()
        user_request_times[chat_id] = [t for t in user_request_times[chat_id] if now - t < RATE_LIMIT_WINDOW]
        return RATE_LIMIT_REQUESTS - len(user_request_times[chat_id])

# --- TIME FUNCTIONS ---
def get_melbourne_time():
    return datetime.datetime.now(MELBOURNE_TZ)

def update_last_check_time():
    global last_check_string
    t = get_melbourne_time()
    last_check_string = t.strftime('%I:%M %p')

def get_time_since_last_slot():
    global last_slot_found_time
    if last_slot_found_time is None:
        return "No slots found yet"
    
    now = get_melbourne_time()
    diff = now - last_slot_found_time
    total_seconds = int(diff.total_seconds())
    
    if total_seconds < 60:
        return f"{total_seconds} seconds ago"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        days = total_seconds // 86400
        return f"{days} day{'s' if days != 1 else ''} ago"

# --- TELEGRAM CORE FUNCTIONS ---
def delete_message(chat_id, message_id):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
        requests.post(url, json={"chat_id": chat_id, "message_id": message_id}, timeout=5)
    except Exception as e:
        print(f"Error deleting message: {e}")

def send_message_raw(chat_id, text, reply_markup=None):
    """Send a message and return the message_id."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                return result.get('result', {}).get('message_id')
        else:
            print(f"Send message failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error sending message: {e}")
    return None

def edit_message_raw(chat_id, message_id, text):
    """Edit a message. Returns True if successful."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return response.json().get('ok', False)
        return False
    except Exception as e:
        print(f"Error editing message: {e}")
        return False

# --- SINGLE MESSAGE MANAGEMENT ---
def show_content(chat_id, text):
    """
    Show content in the single content message.
    Edits existing message or creates new one with keyboard.
    """
    # Try to edit existing content message
    if chat_id in chat_content_message:
        if edit_message_raw(chat_id, chat_content_message[chat_id], text):
            return
        # Edit failed, delete old message
        delete_message(chat_id, chat_content_message[chat_id])
        del chat_content_message[chat_id]
    
    # Send new message with keyboard (needed when message was deleted)
    msg_id = send_message_raw(chat_id, text, REPLY_KEYBOARD)
    if msg_id:
        chat_content_message[chat_id] = msg_id

def show_auth_prompt(chat_id):
    """Show password prompt - NO keyboard."""
    # Remove any existing content
    if chat_id in chat_content_message:
        delete_message(chat_id, chat_content_message[chat_id])
        del chat_content_message[chat_id]
    
    text = "🔐 <b>Authentication Required</b>\n\nThis bot is private. Please enter the password:"
    msg_id = send_message_raw(chat_id, text, REMOVE_KEYBOARD)
    if msg_id:
        chat_content_message[chat_id] = msg_id

def show_wrong_password(chat_id):
    """Show wrong password message - NO keyboard."""
    text = "❌ <b>Incorrect password</b>\n\nPlease try again:"
    if chat_id in chat_content_message:
        edit_message_raw(chat_id, chat_content_message[chat_id], text)
    else:
        msg_id = send_message_raw(chat_id, text, REMOVE_KEYBOARD)
        if msg_id:
            chat_content_message[chat_id] = msg_id

def show_welcome(chat_id):
    """Show welcome message WITH keyboard."""
    # Delete old message first
    if chat_id in chat_content_message:
        delete_message(chat_id, chat_content_message[chat_id])
        del chat_content_message[chat_id]
    
    text = """✅ <b>Authentication successful!</b>

Welcome to the <b>Hair Appointment Bot</b> ✂️

<b>How it works:</b>
- I check for appointments every 2 minutes
- You get notified when slots open up
- Use the buttons below to interact

<i>The menu is now at the bottom of your screen!</i>"""
    
    msg_id = send_message_raw(chat_id, text, REPLY_KEYBOARD)
    if msg_id:
        chat_content_message[chat_id] = msg_id

def show_unsubscribed(chat_id):
    """Show unsubscribed message and REMOVE keyboard."""
    if chat_id in chat_content_message:
        delete_message(chat_id, chat_content_message[chat_id])
        del chat_content_message[chat_id]
    
    text = "🔕 <b>Unsubscribed</b>\n\nYou will no longer receive notifications.\n\nSend any message to re-subscribe."
    send_message_raw(chat_id, text, REMOVE_KEYBOARD)

# --- COMMAND HANDLERS ---
def handle_status(chat_id):
    text = f"""📊 <b>Bot Status</b>

🤖 Status: <b>Running</b>
🕐 Last check: <b>{last_check_string}</b>
📅 Last slot: <b>{get_time_since_last_slot()}</b>
🔍 Monitoring: Next 30 days
👥 Active users: {len(active_chat_ids)}
🔢 Requests left: {get_rate_limit_remaining(chat_id)}/{RATE_LIMIT_REQUESTS}"""
    show_content(chat_id, text)

def handle_check_now(chat_id):
    # Show loading
    show_content(chat_id, "🔍 <b>Checking next 3 months...</b>\n\n⏳ Please wait...")
    
    # Do the check
    found_any, results = do_slot_check(full_check=True)
    
    if found_any:
        text = format_results_simple(results)
    else:
        text = """❌ <b>No slots found</b>

No appointments available in the next 3 months.

I'll notify you automatically when something opens up!"""
    
    show_content(chat_id, text)

def handle_haircut_advice(chat_id):
    advice = random.choice(HAIRCUT_ADVICE)
    text = f"""✂️ <b>Haircut Wisdom</b>

<i>"{advice}"</i>"""
    show_content(chat_id, text)

def handle_stop(chat_id):
    active_chat_ids.discard(chat_id)
    save_users()
    show_unsubscribed(chat_id)

def handle_resubscribe(chat_id):
    active_chat_ids.add(chat_id)
    save_users()
    text = """🔔 <b>Re-subscribed!</b>

You'll now receive notifications when slots open up.

Use the buttons below to interact."""
    show_content(chat_id, text)

# --- APPOINTMENT CHECKING ---
def set_service_session(service_id):
    url = f"https://book.gettimely.com/Booking/Service?obg={BUSINESS_ID}"
    payload = {
        "OnlineBookingMultiServiceEnabled": "True",
        "LocationId": "0",
        "BookableTimeSlotItemIds": service_id
    }
    payload[f"ServiceStaffIds[{service_id}]"] = STAFF_ID
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        response = session.post(url, data=payload, headers=headers, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error setting service: {e}")
        return False

def parse_time_to_minutes(time_str):
    time_str = time_str.upper().replace(" ", "")
    match = re.match(r'(\d{1,2}):(\d{2})(AM|PM)', time_str)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    period = match.group(3)
    if period == 'PM' and hours != 12:
        hours += 12
    elif period == 'AM' and hours == 12:
        hours = 0
    return hours * 60 + minutes

def get_specific_times(date_str):
    url = "https://book.gettimely.com/booking/gettimeslots"
    params = {"obg": BUSINESS_ID, "dateSelected": date_str, "staffId": "-1", "tzId": "57"}
    try:
        response = session.get(url, params=params, timeout=10)
        times = re.findall(r'\d{1,2}:\d{2}\s*(?:am|pm)', response.text, re.IGNORECASE)
        normalised = [t.replace(" ", "").upper() for t in times]
        unique = sorted(list(set(normalised)), key=parse_time_to_minutes)
        return unique[0] if unique else None
    except Exception as e:
        print(f"Error getting times: {e}")
        return None

def check_service_month(year, month):
    url = "https://book.gettimely.com/Booking/GetOpenDates"
    params = {"obg": BUSINESS_ID, "month": month, "year": year, "staffId": "-1", "tzId": "57"}
    try:
        response = session.get(url, params=params, timeout=10)
        data = response.json()
        found = []
        if isinstance(data, dict) and "openDates" in data:
            for item in data["openDates"]:
                if "day" in item:
                    found.append(item["day"])
        return found
    except Exception as e:
        print(f"Error checking month: {e}")
        return []

def do_slot_check(full_check=False):
    global last_slot_found_time
    
    melbourne_time = get_melbourne_time()
    today = melbourne_time.date()
    results = defaultdict(list)
    found_any = False
    
    months_to_check = []
    current_month = today.month
    current_year = today.year
    
    if full_check:
        for i in range(3):
            target_month = current_month + i
            target_year = current_year
            if target_month > 12:
                target_month -= 12
                target_year += 1
            months_to_check.append((target_year, target_month))
    else:
        cutoff = today + datetime.timedelta(days=30)
        months_to_check.append((current_year, current_month))
        next_month = current_month + 1
        next_year = current_year
        if next_month > 12:
            next_month = 1
            next_year += 1
        months_to_check.append((next_year, next_month))
    
    for service_name, service_id in SERVICES_TO_CHECK.items():
        print(f"Checking {service_name}...")
        session.cookies.clear()
        
        if not set_service_session(service_id):
            print(f"Failed to set session for {service_name}")
            continue

        for year, month in months_to_check:
            dates = check_service_month(year, month)
            if dates:
                for d_str in dates:
                    d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
                    
                    if full_check:
                        if d_obj.month != month:
                            continue
                    else:
                        cutoff = today + datetime.timedelta(days=30)
                        if d_obj < today or d_obj > cutoff:
                            continue
                    
                    time_str = get_specific_times(d_str)
                    if time_str:
                        found_any = True
                        results[service_name].append((d_obj, time_str))
                    time.sleep(0.3)
        time.sleep(0.5)
    
    update_last_check_time()
    if found_any:
        last_slot_found_time = get_melbourne_time()
    
    return found_any, results

def format_results_simple(results):
    msg = "🎉 <b>Slots Found!</b>\n"
    for service_name, slots in results.items():
        if slots:
            msg += f"\n<b>{service_name}</b>\n"
            for date_obj, time_str in sorted(slots, key=lambda x: x[0]):
                nice_date = f"{date_obj.day} {date_obj.strftime('%B')}"
                msg += f"• {nice_date}: {time_str}\n"
    msg += "\n<a href='https://bookings.gettimely.com/hairbytaras/book'>📅 Book Now</a>"
    return msg

def broadcast_slots(message):
    for chat_id in list(active_chat_ids):
        if chat_id in authenticated_users:
            show_content(chat_id, message)

# --- BACKGROUND CHECK LOOP ---
def automated_check_loop():
    print("Starting automated check loop...")
    last_slots_found = False
    
    while True:
        try:
            print(f"\n--- Auto Check at {get_melbourne_time().strftime('%I:%M %p')} ---")
            found_any, results = do_slot_check(full_check=False)
            
            if found_any and not last_slots_found:
                print("NEW SLOTS! Notifying...")
                broadcast_slots(format_results_simple(results))
                last_slots_found = True
            elif not found_any:
                print("No slots")
                last_slots_found = False
            
            # Daily report at 7 PM
            mt = get_melbourne_time()
            if mt.hour == 19 and mt.minute < 2:
                report = f"""📊 <b>Daily Report</b>

🤖 Bot running normally
🕐 Last check: {last_check_string}
📅 Last slot: {get_time_since_last_slot()}"""
                broadcast_slots(report)
            
            save_users()
        except Exception as e:
            print(f"Error in check loop: {e}")
        
        time.sleep(CHECK_INTERVAL)

# --- MAIN BOT LOOP ---
def handle_telegram_updates():
    print("Starting Telegram bot...")
    load_users()
    
    # Notify existing users about restart
    time.sleep(2)
    for chat_id in list(active_chat_ids):
        if chat_id in authenticated_users:
            show_content(chat_id, "🔄 <b>Bot Restarted</b>\n\nI'm back online and monitoring for slots!")
    
    offset = None
    errors = 0
    
    tg_session = requests.Session()
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset
            
            response = tg_session.get(url, params=params, timeout=40)
            
            if response.status_code != 200:
                print(f"HTTP error: {response.status_code}")
                errors += 1
                time.sleep(5)
                continue
            
            data = response.json()
            if not data.get('ok'):
                print(f"API error: {data}")
                errors += 1
                time.sleep(5)
                continue
            
            errors = 0
            
            for update in data.get('result', []):
                offset = update['update_id'] + 1
                
                if 'message' not in update:
                    continue
                
                msg = update['message']
                chat_id = msg['chat']['id']
                msg_id = msg['message_id']
                text = msg.get('text', '').strip()
                
                # Delete user message to keep chat clean
                Thread(target=lambda: (time.sleep(0.2), delete_message(chat_id, msg_id)), daemon=True).start()
                
                # === NOT AUTHENTICATED ===
                if chat_id not in authenticated_users:
                    if text == BOT_PASSWORD:
                        # Correct password!
                        authenticated_users.add(chat_id)
                        active_chat_ids.add(chat_id)
                        save_users()
                        show_welcome(chat_id)
                    else:
                        # Wrong password or /start
                        if text.lower() == '/start':
                            show_auth_prompt(chat_id)
                        else:
                            show_wrong_password(chat_id)
                    continue
                
                # === AUTHENTICATED ===
                
                # Rate limit check
                if not check_rate_limit(chat_id):
                    show_content(chat_id, "⚠️ <b>Rate Limited</b>\n\nPlease wait a moment...")
                    continue
                
                # If unsubscribed, re-subscribe on any message
                if chat_id not in active_chat_ids:
                    handle_resubscribe(chat_id)
                    continue
                
                # Handle menu buttons
                if text == "📊 Status":
                    handle_status(chat_id)
                elif text == "🔍 Check Now":
                    handle_check_now(chat_id)
                elif text == "✂️ Haircut Advice":
                    handle_haircut_advice(chat_id)
                elif text == "🔕 Stop Notifications":
                    handle_stop(chat_id)
                elif text.lower() == '/start':
                    handle_status(chat_id)
                else:
                    # Unknown input - show status
                    handle_status(chat_id)
        
        except requests.exceptions.Timeout:
            errors += 1
            time.sleep(2)
        except requests.exceptions.ConnectionError:
            errors += 1
            tg_session = requests.Session()
            time.sleep(5)
        except Exception as e:
            print(f"Error: {e}")
            errors += 1
            time.sleep(5)
        
        if errors >= 5:
            print("Too many errors, resetting...")
            tg_session = requests.Session()
            time.sleep(30)
            errors = 0

# --- MAIN ---
if __name__ == "__main__":
    print("=" * 50)
    print("Hair Appointment Bot")
    print("=" * 50)
    
    # Start Flask
    Thread(target=run_http_server, daemon=False).start()
    time.sleep(3)
    
    # Start auto-checker
    Thread(target=automated_check_loop, daemon=True).start()
    
    # Start bot
    handle_telegram_updates()
