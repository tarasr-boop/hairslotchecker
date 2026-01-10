import requests
import os
import datetime
import time
import re
from collections import defaultdict
import pytz
import random
import json
import hashlib
from threading import Thread, Lock
from flask import Flask
import sys

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not BOT_TOKEN:
    print("ERROR: TELEGRAM_TOKEN environment variable not set!", file=sys.stderr)
    raise Exception("TELEGRAM_TOKEN environment variable not set!")

print(f"Bot token loaded: {BOT_TOKEN[:10]}...", flush=True)

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

# --- JSONBIN STORAGE (FREE PERSISTENT STORAGE) ---
# Sign up at https://jsonbin.io and get your API key
JSONBIN_API_KEY = os.environ.get('JSONBIN_API_KEY', '')
JSONBIN_BIN_ID = os.environ.get('JSONBIN_BIN_ID', '')  # Create a bin and put ID here

# Global variables
active_chat_ids = set()
authenticated_users = set()
last_check_string = "Not checked yet"
last_slot_found_time = None
last_slots_hash = None  # Track slot changes by hash
user_request_times = defaultdict(list)
rate_limit_lock = Lock()
chat_content_message = {}
storage_lock = Lock()

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

# --- HELPER FUNCTION FOR LOGGING ---
def log(message):
    """Print with flush for immediate output on Render"""
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)

# --- PERSISTENT STORAGE (JSONBin.io - FREE) ---
def save_users():
    """Save users to JSONBin (persistent) with fallback to local file"""
    with storage_lock:
        data = {
            "active_chat_ids": list(active_chat_ids),
            "authenticated_users": list(authenticated_users),
            "last_slots_hash": last_slots_hash,
            "updated_at": datetime.datetime.now().isoformat()
        }
        
        # Try JSONBin first (persistent across restarts)
        if JSONBIN_API_KEY and JSONBIN_BIN_ID:
            try:
                response = requests.put(
                    f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}",
                    json=data,
                    headers={
                        "X-Master-Key": JSONBIN_API_KEY,
                        "Content-Type": "application/json"
                    },
                    timeout=10
                )
                if response.status_code == 200:
                    log(f"✅ Saved {len(active_chat_ids)} users to JSONBin")
                    return
                else:
                    log(f"⚠️ JSONBin save failed: {response.status_code}")
            except Exception as e:
                log(f"⚠️ JSONBin error: {e}")
        
        # Fallback to local file (will be lost on restart)
        try:
            with open("active_users.json", 'w') as f:
                json.dump(data, f)
            log(f"⚠️ Saved to local file (not persistent on Render!)")
        except Exception as e:
            log(f"❌ Error saving users: {e}")

def load_users():
    """Load users from JSONBin (persistent) with fallback to local file"""
    global active_chat_ids, authenticated_users, last_slots_hash
    
    with storage_lock:
        # Try JSONBin first
        if JSONBIN_API_KEY and JSONBIN_BIN_ID:
            try:
                response = requests.get(
                    f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest",
                    headers={"X-Master-Key": JSONBIN_API_KEY},
                    timeout=10
                )
                if response.status_code == 200:
                    data = response.json().get('record', {})
                    active_chat_ids = set(data.get("active_chat_ids", []))
                    authenticated_users = set(data.get("authenticated_users", []))
                    last_slots_hash = data.get("last_slots_hash")
                    log(f"✅ Loaded {len(active_chat_ids)} users from JSONBin")
                    return
            except Exception as e:
                log(f"⚠️ JSONBin load error: {e}")
        
        # Fallback to local file
        try:
            if os.path.exists("active_users.json"):
                with open("active_users.json", 'r') as f:
                    data = json.load(f)
                    active_chat_ids = set(data.get("active_chat_ids", []))
                    authenticated_users = set(data.get("authenticated_users", []))
                    last_slots_hash = data.get("last_slots_hash")
                log(f"⚠️ Loaded {len(active_chat_ids)} users from local file")
        except Exception as e:
            log(f"❌ Error loading users: {e}")

# --- FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return f"""
    <html>
    <head><title>Hair Bot Status</title></head>
    <body>
        <h1>Hair Appointment Bot</h1>
        <p>Status: ✅ Running</p>
        <p>Active users: {len(active_chat_ids)}</p>
        <p>Last check: {last_check_string}</p>
        <p>Last slot: {get_time_since_last_slot()}</p>
    </body>
    </html>
    """

@app.route('/health')
def health():
    return "OK", 200

@app.route('/ping')
def ping():
    """Endpoint for external uptime monitors to ping"""
    return json.dumps({
        "status": "alive",
        "users": len(active_chat_ids),
        "last_check": last_check_string,
        "timestamp": datetime.datetime.now().isoformat()
    }), 200, {'Content-Type': 'application/json'}

def run_http_server():
    try:
        port = int(os.environ.get("PORT", 8080))
        log(f"Starting Flask server on port {port}...")
        app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
    except Exception as e:
        log(f"Error starting Flask server: {e}")
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
        log(f"Error deleting message: {e}")

def send_message_raw(chat_id, text, reply_markup=None, retry=3):
    """Send a message and return the message_id with retry logic."""
    for attempt in range(retry):
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            if reply_markup:
                payload["reply_markup"] = json.dumps(reply_markup)
            
            log(f"Sending message to {chat_id} (attempt {attempt+1})")
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            
            if result.get('ok'):
                msg_id = result.get('result', {}).get('message_id')
                log(f"Message sent successfully, id={msg_id}")
                return msg_id
            else:
                error = result.get('description', 'Unknown error')
                log(f"Send FAILED: {error}")
                
                # If user blocked the bot, remove them
                if 'blocked' in error.lower() or 'deactivated' in error.lower():
                    active_chat_ids.discard(chat_id)
                    authenticated_users.discard(chat_id)
                    save_users()
                    return None
                    
        except requests.exceptions.Timeout:
            log(f"Timeout on attempt {attempt+1}")
            time.sleep(2 ** attempt)
        except Exception as e:
            log(f"Exception sending message: {e}")
            time.sleep(2 ** attempt)
    
    return None

def edit_message_raw(chat_id, message_id, text, retry=2):
    """Edit a message with retry logic."""
    for attempt in range(retry):
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
            result = response.json()
            
            if result.get('ok'):
                return True
            else:
                error_desc = result.get('description', 'Unknown error')
                if 'message is not modified' in error_desc.lower():
                    return True
                if 'message to edit not found' in error_desc.lower():
                    return False
                log(f"Edit FAILED: {error_desc}")
                
        except Exception as e:
            log(f"Exception editing message: {e}")
            time.sleep(1)
    
    return False

# --- SINGLE MESSAGE MANAGEMENT ---
def show_content(chat_id, text):
    """Show content in the single content message."""
    log(f"show_content called for {chat_id}")
    
    if chat_id in chat_content_message:
        if edit_message_raw(chat_id, chat_content_message[chat_id], text):
            return
        delete_message(chat_id, chat_content_message[chat_id])
        del chat_content_message[chat_id]
    
    msg_id = send_message_raw(chat_id, text, REPLY_KEYBOARD)
    if msg_id:
        chat_content_message[chat_id] = msg_id

def show_auth_prompt(chat_id):
    """Show password prompt - NO keyboard."""
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
    if chat_id in chat_content_message:
        delete_message(chat_id, chat_content_message[chat_id])
        del chat_content_message[chat_id]
    
    text = """✅ <b>Authentication successful!</b>

Welcome to the <b>Hair Appointment Bot</b> ✂️

<b>How it works:</b>
- I check for appointments every 2 minutes
- You get notified when NEW slots open up
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
🔢 Requests left: {get_rate_limit_remaining(chat_id)}/{RATE_LIMIT_REQUESTS}
💾 Storage: {"JSONBin (persistent)" if JSONBIN_API_KEY else "Local (NOT persistent!)"}"""
    show_content(chat_id, text)

def handle_check_now(chat_id):
    show_content(chat_id, "🔍 <b>Checking next 3 months...</b>\n\n⏳ Please wait...")
    
    found_any, results, _ = do_slot_check(full_check=True)
    
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
def set_service_session(service_id, max_retries=3):
    """Set up booking session with retry logic."""
    url = f"https://book.gettimely.com/Booking/Service?obg={BUSINESS_ID}"
    payload = {
        "OnlineBookingMultiServiceEnabled": "True",
        "LocationId": "0",
        "BookableTimeSlotItemIds": service_id
    }
    payload[f"ServiceStaffIds[{service_id}]"] = STAFF_ID
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    for attempt in range(max_retries):
        try:
            response = session.post(url, data=payload, headers=headers, timeout=15)
            if response.status_code == 200:
                return True
            log(f"Service session returned {response.status_code}")
        except requests.exceptions.Timeout:
            log(f"Timeout setting service (attempt {attempt+1})")
        except Exception as e:
            log(f"Error setting service: {e}")
        
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)
    
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

def get_specific_times(date_str, max_retries=2):
    """Get time slots for a specific date with retry logic."""
    url = "https://book.gettimely.com/booking/gettimeslots"
    params = {"obg": BUSINESS_ID, "dateSelected": date_str, "staffId": "-1", "tzId": "57"}
    
    for attempt in range(max_retries):
        try:
            response = session.get(url, params=params, timeout=15)
            times = re.findall(r'\d{1,2}:\d{2}\s*(?:am|pm)', response.text, re.IGNORECASE)
            normalised = [t.replace(" ", "").upper() for t in times]
            unique = sorted(list(set(normalised)), key=lambda x: parse_time_to_minutes(x) or 0)
            return unique[0] if unique else None
        except Exception as e:
            log(f"Error getting times for {date_str}: {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
    
    return None

def check_service_month(year, month, max_retries=2):
    """Check for open dates in a month with retry logic."""
    url = "https://book.gettimely.com/Booking/GetOpenDates"
    params = {"obg": BUSINESS_ID, "month": month, "year": year, "staffId": "-1", "tzId": "57"}
    
    for attempt in range(max_retries):
        try:
            response = session.get(url, params=params, timeout=15)
            data = response.json()
            found = []
            if isinstance(data, dict) and "openDates" in data:
                for item in data["openDates"]:
                    if "day" in item:
                        found.append(item["day"])
            return found
        except json.JSONDecodeError:
            log(f"Invalid JSON response for {month}/{year}")
        except Exception as e:
            log(f"Error checking month {month}/{year}: {e}")
        
        if attempt < max_retries - 1:
            time.sleep(1)
    
    return []

def hash_slots(results):
    """Create a hash of current slots to detect changes."""
    slot_data = []
    for service_name in sorted(results.keys()):
        for date_obj, time_str in sorted(results[service_name], key=lambda x: x[0]):
            slot_data.append(f"{service_name}|{date_obj}|{time_str}")
    
    if not slot_data:
        return None
    
    return hashlib.md5("|".join(slot_data).encode()).hexdigest()

def do_slot_check(full_check=False):
    """
    Check for available slots.
    Returns: (found_any, results, is_new_slots)
    """
    global last_slot_found_time, last_slots_hash
    
    melbourne_time = get_melbourne_time()
    today = melbourne_time.date()
    results = defaultdict(list)
    found_any = False
    
    # Calculate months to check
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
    
    cutoff_date = today + datetime.timedelta(days=30 if not full_check else 90)
    
    for service_name, service_id in SERVICES_TO_CHECK.items():
        log(f"Checking {service_name}...")
        session.cookies.clear()
        
        if not set_service_session(service_id):
            log(f"⚠️ Failed to set session for {service_name}")
            continue

        for year, month in months_to_check:
            dates = check_service_month(year, month)
            if dates:
                for d_str in dates:
                    try:
                        d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    
                    # Filter dates
                    if d_obj < today or d_obj > cutoff_date:
                        continue
                    
                    if full_check and d_obj.month != month:
                        continue
                    
                    time_str = get_specific_times(d_str)
                    if time_str:
                        found_any = True
                        results[service_name].append((d_obj, time_str))
                    time.sleep(0.3)
            time.sleep(0.5)
    
    update_last_check_time()
    
    # Check if slots changed
    current_hash = hash_slots(results) if found_any else None
    is_new_slots = found_any and current_hash != last_slots_hash
    
    if found_any:
        last_slot_found_time = get_melbourne_time()
        last_slots_hash = current_hash
        save_users()  # Save new hash
    
    return found_any, results, is_new_slots

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
    """Broadcast message to all authenticated active users."""
    sent_count = 0
    for chat_id in list(active_chat_ids):
        if chat_id in authenticated_users:
            show_content(chat_id, message)
            sent_count += 1
            time.sleep(0.1)  # Small delay to avoid rate limits
    log(f"Broadcast sent to {sent_count} users")

# --- BACKGROUND CHECK LOOP ---
def automated_check_loop():
    log("Starting automated check loop...")
    consecutive_errors = 0
    
    while True:
        try:
            log(f"--- Auto Check at {get_melbourne_time().strftime('%I:%M %p')} ---")
            found_any, results, is_new_slots = do_slot_check(full_check=False)
            
            if is_new_slots:
                log("🆕 NEW/CHANGED SLOTS! Notifying...")
                broadcast_slots(format_results_simple(results))
            elif found_any:
                log("✅ Slots exist but unchanged")
            else:
                log("❌ No slots")
            
            consecutive_errors = 0
            
            # Daily report at 7 PM
            mt = get_melbourne_time()
            if mt.hour == 19 and mt.minute < 3:
                report = f"""📊 <b>Daily Report</b>

🤖 Bot running normally
🕐 Last check: {last_check_string}
📅 Last slot: {get_time_since_last_slot()}
👥 Active users: {len(active_chat_ids)}"""
                broadcast_slots(report)
            
            save_users()
            
        except Exception as e:
            log(f"❌ Error in check loop: {e}")
            consecutive_errors += 1
            
            # If too many errors, wait longer
            if consecutive_errors >= 5:
                log("⚠️ Too many consecutive errors, waiting 5 minutes...")
                time.sleep(300)
                consecutive_errors = 0
        
        time.sleep(CHECK_INTERVAL)

# --- MAIN BOT LOOP ---
def handle_telegram_updates():
    log("Starting Telegram bot...")
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
                log(f"HTTP error: {response.status_code}")
                errors += 1
                time.sleep(5)
                continue
            
            data = response.json()
            if not data.get('ok'):
                log(f"API error: {data}")
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
                
                log(f"=== Received from {chat_id}: '{text}' ===")
                
                # Delete user message to keep chat clean
                Thread(target=lambda cid=chat_id, mid=msg_id: (time.sleep(0.2), delete_message(cid, mid)), daemon=True).start()
                
                # === NOT AUTHENTICATED ===
                if chat_id not in authenticated_users:
                    if text == BOT_PASSWORD:
                        authenticated_users.add(chat_id)
                        active_chat_ids.add(chat_id)
                        save_users()
                        show_welcome(chat_id)
                    else:
                        if text.lower() == '/start':
                            show_auth_prompt(chat_id)
                        else:
                            show_wrong_password(chat_id)
                    continue
                
                # === AUTHENTICATED ===
                if not check_rate_limit(chat_id):
                    show_content(chat_id, "⚠️ <b>Rate Limited</b>\n\nPlease wait a moment...")
                    continue
                
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
                    handle_status(chat_id)
        
        except requests.exceptions.Timeout:
            log("Timeout")
            errors += 1
            time.sleep(2)
        except requests.exceptions.ConnectionError:
            log("Connection error")
            errors += 1
            tg_session = requests.Session()
            time.sleep(5)
        except Exception as e:
            log(f"Error: {e}")
            import traceback
            traceback.print_exc()
            errors += 1
            time.sleep(5)
        
        if errors >= 5:
            log("Too many errors, resetting...")
            tg_session = requests.Session()
            time.sleep(30)
            errors = 0

# --- MAIN ---
if __name__ == "__main__":
    print("=" * 50, flush=True)
    print("Hair Appointment Bot - FIXED VERSION", flush=True)
    print("=" * 50, flush=True)
    
    if not JSONBIN_API_KEY:
        print("⚠️ WARNING: JSONBIN_API_KEY not set!", flush=True)
        print("⚠️ User data will be LOST on restart!", flush=True)
        print("⚠️ Get free API key at https://jsonbin.io", flush=True)
    
    # Start Flask
    Thread(target=run_http_server, daemon=False).start()
    time.sleep(3)
    
    # Start auto-checker
    Thread(target=automated_check_loop, daemon=True).start()
    
    # Start bot
    handle_telegram_updates()
