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

# Password for bot access
BOT_PASSWORD = "password"

BUSINESS_ID = "8ab07528-c2a9-463d-a441-3e0aa39a975e"
STAFF_ID = "339008"

SERVICES_TO_CHECK = {
    "👦 Short hair (1 hour)": "1802687:SV",
    "👧 Long hair (1.5 hours)": "1802702:SV"
}

# Melbourne timezone
MELBOURNE_TZ = pytz.timezone('Australia/Melbourne')

# Check interval in seconds (2 minutes)
CHECK_INTERVAL = 120

# Rate limiting: max 20 requests per minute per user
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW = 60  # seconds

# File to persist active users
USERS_FILE = "active_users.json"

# Global variables
active_chat_ids = set()
authenticated_users = set()
last_check_string = "Not checked yet"
last_slot_found_time = None
user_request_times = defaultdict(list)
rate_limit_lock = Lock()

# Track the SINGLE content message per chat
chat_content_message = {}  # {chat_id: message_id}

# --- ONE-LINERS (Shuffled on startup) ---

# Esoteric one-liners
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

# Witty one-liners
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

# Consulting one-liners
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
    "You're one haircut away from thought leadership.",
    "I've benchmarked your hair against industry standards. It's lagging.",
    "This is a change management issue. The change is: shorter hair.",
    "The SWOT analysis is complete. Your hair is a weakness.",
    "Let's action this: book the appointment.",
    "Time to sunset your current hairstyle.",
    "Let's move the needle here. The needle is scissors.",
]

# Combine and shuffle all one-liners
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

# --- PERSISTENT KEYBOARD DEFINITION ---
def get_persistent_keyboard():
    """Returns the persistent reply keyboard markup."""
    return {
        "keyboard": [
            [{"text": "📊 Status"}, {"text": "🔍 Check Now"}],
            [{"text": "✂️ Haircut Advice"}],
            [{"text": "🔕 Stop Notifications"}]
        ],
        "resize_keyboard": True,
        "persistent": True,
        "input_field_placeholder": "Tap a button below..."
    }

def get_remove_keyboard():
    """Returns markup to remove the keyboard."""
    return {"remove_keyboard": True}

# --- PERSISTENCE FUNCTIONS ---
def save_users():
    """Save active users to file for persistence across restarts."""
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
    """Load active users from file."""
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

# --- FLASK SERVER TO KEEP RENDER ALIVE ---
app = Flask(__name__)

@app.route('/')
def home():
    return f"Bot is alive! Active users: {len(active_chat_ids)}"

@app.route('/health')
def health():
    return "OK", 200

def run_http_server():
    """Run Flask server for Render health checks."""
    try:
        port = int(os.environ.get("PORT", 8080))
        print(f"Starting Flask server on port {port}...")
        app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
    except Exception as e:
        print(f"Error starting Flask server: {e}", file=sys.stderr)
        raise

# --- RATE LIMITING ---
def check_rate_limit(chat_id):
    """Check if user is within rate limit. Returns True if allowed, False if rate limited."""
    with rate_limit_lock:
        now = time.time()
        user_request_times[chat_id] = [t for t in user_request_times[chat_id] if now - t < RATE_LIMIT_WINDOW]
        
        if len(user_request_times[chat_id]) >= RATE_LIMIT_REQUESTS:
            return False
        
        user_request_times[chat_id].append(now)
        return True

def get_rate_limit_remaining(chat_id):
    """Get how many requests remaining for user."""
    with rate_limit_lock:
        now = time.time()
        user_request_times[chat_id] = [t for t in user_request_times[chat_id] if now - t < RATE_LIMIT_WINDOW]
        return RATE_LIMIT_REQUESTS - len(user_request_times[chat_id])

# --- TIME FUNCTIONS ---
def get_melbourne_time():
    """Get current time in Melbourne timezone."""
    return datetime.datetime.now(MELBOURNE_TZ)

def update_last_check_time():
    """Updates the global variable with current Melbourne time."""
    global last_check_string
    t = get_melbourne_time()
    last_check_string = t.strftime('%I:%M %p')

def get_time_since_last_slot():
    """Get human-readable time since last slot was found."""
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

# --- MESSAGE FUNCTIONS ---
def delete_message(chat_id, message_id):
    """Delete a message from chat."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Error deleting message: {e}")

def delete_user_message(chat_id, message_id):
    """Delete a user's message."""
    try:
        delete_message(chat_id, message_id)
    except Exception as e:
        print(f"Error deleting user message: {e}")

# --- TELEGRAM FUNCTIONS ---
def send_message(chat_id, text, reply_markup=None, retries=3):
    """Send message to a specific chat with retry logic."""
    for attempt in range(retries):
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
            
            if attempt < retries - 1:
                time.sleep(2)
                continue
                
        except Exception as e:
            print(f"Error sending message (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2)
            
    return None

def edit_message(chat_id, message_id, text, reply_markup=None):
    """Edit an existing message."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            return result.get('ok', False)
        return False
    except Exception as e:
        print(f"Error editing message: {e}")
        return False

def update_content_message(chat_id, text, show_keyboard=True):
    """
    Update the single content message for a chat.
    - If message exists, try to edit it
    - If edit fails or no message exists, delete old and send new
    """
    reply_markup = get_persistent_keyboard() if show_keyboard else None
    
    # Try to edit existing message first
    if chat_id in chat_content_message:
        old_msg_id = chat_content_message[chat_id]
        if edit_message(chat_id, old_msg_id, text, reply_markup):
            return old_msg_id
        else:
            # Edit failed (message too old, deleted, or content same)
            # Delete old message and send new
            delete_message(chat_id, old_msg_id)
    
    # Send new message
    new_msg_id = send_message(chat_id, text, reply_markup)
    if new_msg_id:
        chat_content_message[chat_id] = new_msg_id
    return new_msg_id

def show_loading_then_content(chat_id, loading_text, final_text_func):
    """
    Show loading message, perform action, then update with result.
    final_text_func should be a callable that returns the final text.
    """
    # Show loading state
    update_content_message(chat_id, loading_text)
    
    # Get the final content
    final_text = final_text_func()
    
    # Update with final content
    update_content_message(chat_id, final_text)

def send_password_prompt(chat_id):
    """Send password prompt to unauthenticated user (no keyboard)."""
    message = "🔐 <b>Authentication Required</b>\n\nThis bot is private. Please enter the password to continue:"
    # Remove keyboard for unauthenticated users
    msg_id = send_message(chat_id, message, get_remove_keyboard())
    if msg_id:
        chat_content_message[chat_id] = msg_id

def send_welcome_message(chat_id):
    """Send welcome message with bot introduction after authentication."""
    intro = """✅ <b>Authentication successful!</b>

Welcome to the <b>Hair Appointment Bot</b> ✂️

<b>How it works:</b>
- I automatically check the booking website every 2 minutes
- If a slot becomes available, I'll notify you immediately
- If nothing is found, I stay quiet (no spam!)

<b>Use the menu below to:</b>
- Check bot status
- Manually search for slots
- Get haircut wisdom

Let's find you an appointment!"""
    
    update_content_message(chat_id, intro)

def send_home_screen(chat_id):
    """Send the default home screen."""
    home_text = """✂️ <b>Hair Appointment Bot</b>

🤖 Status: <b>Monitoring</b>
🕐 Last check: <b>{}</b>
📅 Last slot: <b>{}</b>

<i>Use the menu below to interact.</i>""".format(last_check_string, get_time_since_last_slot())
    
    update_content_message(chat_id, home_text)

def answer_callback(callback_query_id, text=None):
    """Answer a callback query."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Error answering callback: {e}")

# --- APPOINTMENT CHECKING FUNCTIONS ---
def set_service_session(service_id):
    """Lock service into session."""
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
    """Convert time to minutes since midnight."""
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
    """Get available time slots for a date."""
    url = "https://book.gettimely.com/booking/gettimeslots"
    params = {
        "obg": BUSINESS_ID,
        "dateSelected": date_str,
        "staffId": "-1",
        "tzId": "57"
    }

    try:
        response = session.get(url, params=params, timeout=10)
        times = re.findall(r'\d{1,2}:\d{2}\s*(?:am|pm)', response.text, re.IGNORECASE)
        
        normalised_times = [t.replace(" ", "").upper() for t in times]
        unique_times = sorted(list(set(normalised_times)), key=parse_time_to_minutes)
        
        if unique_times:
            return unique_times[0]
        return None
    except Exception as e:
        print(f"Error getting times: {e}")
        return None

def check_service_month(year, month):
    """Check available dates in a month."""
    url = "https://book.gettimely.com/Booking/GetOpenDates"
    params = {
        "obg": BUSINESS_ID,
        "month": month,
        "year": year,
        "staffId": "-1",
        "tzId": "57"
    }

    try:
        response = session.get(url, params=params, timeout=10)
        data = response.json()
        
        found_dates = []
        if isinstance(data, dict) and "openDates" in data:
            for item in data["openDates"]:
                if "day" in item:
                    found_dates.append(item["day"])
        return found_dates
    except Exception as e:
        print(f"Error checking month: {e}")
        return []

def do_slot_check(full_check=False):
    """Check for available slots."""
    global last_slot_found_time
    
    melbourne_time = get_melbourne_time()
    today = melbourne_time.date()
    
    results = defaultdict(list)
    found_any_slots = False
    
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
        cutoff_date = today + datetime.timedelta(days=30)
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
                        if d_obj < today or d_obj > cutoff_date:
                            continue
                    
                    time_str = get_specific_times(d_str)
                    
                    if not time_str:
                        continue

                    found_any_slots = True
                    results[service_name].append((d_obj, time_str))
                    
                    time.sleep(0.3)
        
        time.sleep(0.5)
    
    update_last_check_time()
    
    if found_any_slots:
        last_slot_found_time = get_melbourne_time()

    return found_any_slots, results

def format_results_simple(results):
    """Format results in simple format without month grouping."""
    final_msg = "🎉 <b>Slots Found!</b>\n"
    
    for service_name, slots in results.items():
        if slots:
            final_msg += f"\n<b>{service_name}</b>\n\n"
            
            sorted_slots = sorted(slots, key=lambda x: x[0])
            
            for date_obj, time_str in sorted_slots:
                nice_date = f"{date_obj.day} {date_obj.strftime('%B')}"
                final_msg += f"• {nice_date}: {time_str}\n"

    final_msg += "\n<a href='https://bookings.gettimely.com/hairbytaras/book'>📅 Book Now</a>"
    return final_msg

def broadcast_to_users(message):
    """Send message to all active authenticated users (updates their content message)."""
    for chat_id in list(active_chat_ids):
        if chat_id in authenticated_users:
            update_content_message(chat_id, message)

def notify_restart():
    """Notify users that the bot has restarted."""
    restart_msg = """🔄 <b>Bot Restarted</b>

I'm back online and monitoring for available slots.

You'll receive notifications when appointments become available.

<i>Use the menu below to interact.</i>"""
    for chat_id in list(active_chat_ids):
        if chat_id in authenticated_users:
            update_content_message(chat_id, restart_msg)

# --- BACKGROUND THREADS ---
def automated_check_loop():
    """Background thread that checks every 2 minutes."""
    print("Starting automated check loop (every 2 minutes)...")
    last_slots_found = False
    
    while True:
        try:
            print(f"\n--- Automated Check at {get_melbourne_time().strftime('%I:%M %p')} ---")
            
            found_any_slots, results = do_slot_check(full_check=False)
            
            if found_any_slots and not last_slots_found:
                print("NEW SLOTS FOUND! Notifying users...")
                message = format_results_simple(results)
                broadcast_to_users(message)
                last_slots_found = True
            elif not found_any_slots:
                print("No slots found")
                last_slots_found = False
            else:
                print("Slots still available (no new notification)")
            
            melbourne_time = get_melbourne_time()
            if melbourne_time.hour == 19 and melbourne_time.minute < 2:
                status_msg = f"""📊 <b>Daily Report</b>

🤖 Bot running normally
🕐 Last check: {last_check_string}
📅 Last slot found: {get_time_since_last_slot()}

<i>Use the menu below to interact.</i>"""
                broadcast_to_users(status_msg)
            
            save_users()
            
        except Exception as e:
            print(f"Error in automated check: {e}")
        
        time.sleep(CHECK_INTERVAL)

# --- COMMAND HANDLERS ---
def handle_status(chat_id):
    """Handle status request."""
    status_msg = f"""📊 <b>Bot Status</b>

🤖 Status: <b>Running</b>
🕐 Last check: <b>{last_check_string}</b>
📅 Last slot found: <b>{get_time_since_last_slot()}</b>
🔍 Monitoring: Next 30 days

👥 Active users: {len(active_chat_ids)}
🔢 Your requests: {get_rate_limit_remaining(chat_id)}/{RATE_LIMIT_REQUESTS} remaining

<i>Use the menu below to interact.</i>"""
    update_content_message(chat_id, status_msg)

def handle_check_now(chat_id):
    """Handle manual check request."""
    # Show loading state
    update_content_message(chat_id, "🔍 <b>Checking next 3 months...</b>\n\n⏳ This may take a moment...")
    
    # Perform the check
    found_any_slots, results = do_slot_check(full_check=True)
    
    # Show results
    if found_any_slots:
        message = format_results_simple(results)
        message += "\n\n<i>Use the menu below to interact.</i>"
    else:
        message = """❌ <b>No slots found</b>

No appointments available in the next 3 months.

I'll notify you automatically when something opens up!

<i>Use the menu below to interact.</i>"""
    
    update_content_message(chat_id, message)

def handle_haircut_advice(chat_id):
    """Handle haircut advice request."""
    advice = random.choice(HAIRCUT_ADVICE)
    message = f"""✂️ <b>Haircut Wisdom</b>

<i>"{advice}"</i>

<i>Use the menu below for more options.</i>"""
    update_content_message(chat_id, message)

def handle_stop_notifications(chat_id):
    """Handle stop notifications request."""
    active_chat_ids.discard(chat_id)
    save_users()
    
    message = """🔕 <b>Unsubscribed</b>

You will no longer receive automatic notifications.

Send any message to re-subscribe."""
    
    # Remove the keyboard when unsubscribed
    if chat_id in chat_content_message:
        delete_message(chat_id, chat_content_message[chat_id])
        del chat_content_message[chat_id]
    
    send_message(chat_id, message, get_remove_keyboard())

# --- MAIN BOT LOOP ---
def handle_telegram_updates():
    """Main bot loop - handles messages from reply keyboard."""
    print("Starting Telegram bot...")
    
    load_users()
    
    time.sleep(2)
    
    if active_chat_ids:
        print("Notifying users about restart...")
        notify_restart()
    
    offset = None
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    telegram_session = requests.Session()
    telegram_session.headers.update({
        "Connection": "keep-alive"
    })
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {
                "timeout": 30,
                "allowed_updates": ["message"]  # Only need messages now (reply keyboard sends messages)
            }
            if offset:
                params["offset"] = offset
            
            response = telegram_session.get(url, params=params, timeout=40)
            
            if response.status_code != 200:
                print(f"HTTP error: {response.status_code}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print("Too many errors, recreating session...")
                    telegram_session = requests.Session()
                    telegram_session.headers.update({"Connection": "keep-alive"})
                    consecutive_errors = 0
                time.sleep(5)
                continue
            
            data = response.json()
            
            if not data.get('ok'):
                print(f"Telegram API error: {data.get('description', 'Unknown error')}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print("Too many errors, recreating session...")
                    telegram_session = requests.Session()
                    telegram_session.headers.update({"Connection": "keep-alive"})
                    consecutive_errors = 0
                time.sleep(5)
                continue
            
            consecutive_errors = 0
            
            updates = data.get('result', [])
            
            for update in updates:
                offset = update['update_id'] + 1
                
                if 'message' in update:
                    message = update['message']
                    chat_id = message['chat']['id']
                    user_message_id = message['message_id']
                    text = message.get('text', '').strip()
                    
                    # Always delete user messages to keep chat clean
                    Thread(target=lambda mid=user_message_id, cid=chat_id: (time.sleep(0.2), delete_user_message(cid, mid)), daemon=True).start()
                    
                    # --- AUTHENTICATION ---
                    if chat_id not in authenticated_users:
                        if text.lower() == '/start':
                            send_password_prompt(chat_id)
                            continue
                        
                        if text == BOT_PASSWORD:
                            authenticated_users.add(chat_id)
                            active_chat_ids.add(chat_id)
                            save_users()
                            send_welcome_message(chat_id)
                        else:
                            # Wrong password
                            msg = "❌ <b>Incorrect password</b>\n\nPlease try again:"
                            if chat_id in chat_content_message:
                                edit_message(chat_id, chat_content_message[chat_id], msg)
                            else:
                                msg_id = send_message(chat_id, msg, get_remove_keyboard())
                                if msg_id:
                                    chat_content_message[chat_id] = msg_id
                        continue
                    
                    # --- RATE LIMITING ---
                    if not check_rate_limit(chat_id):
                        update_content_message(chat_id, f"⚠️ <b>Rate Limited</b>\n\nPlease wait before making more requests.\n\nLimit: {RATE_LIMIT_REQUESTS} requests per minute.")
                        continue
                    
                    # --- RE-SUBSCRIBE IF NEEDED ---
                    if chat_id not in active_chat_ids:
                        active_chat_ids.add(chat_id)
                        save_users()
                        update_content_message(chat_id, "🔔 <b>Re-subscribed!</b>\n\nYou'll now receive notifications again.\n\n<i>Use the menu below to interact.</i>")
                        continue
                    
                    # --- HANDLE MENU BUTTONS (Reply Keyboard sends text) ---
                    if text == "📊 Status":
                        handle_status(chat_id)
                    
                    elif text == "🔍 Check Now":
                        handle_check_now(chat_id)
                    
                    elif text == "✂️ Haircut Advice":
                        handle_haircut_advice(chat_id)
                    
                    elif text == "🔕 Stop Notifications":
                        handle_stop_notifications(chat_id)
                    
                    elif text.lower() == '/start':
                        send_home_screen(chat_id)
                    
                    else:
                        # Unknown text - just show home screen
                        send_home_screen(chat_id)
            
            if offset and offset % 30 == 0:
                print(f"Bot alive - processed {offset} updates")
        
        except requests.exceptions.Timeout:
            print("Request timeout - retrying...")
            consecutive_errors += 1
            time.sleep(2)
            
        except requests.exceptions.ConnectionError as e:
            print(f"Connection error: {e} - retrying...")
            consecutive_errors += 1
            telegram_session = requests.Session()
            telegram_session.headers.update({"Connection": "keep-alive"})
            time.sleep(5)
            
        except Exception as e:
            print(f"Unexpected error: {e}")
            consecutive_errors += 1
            time.sleep(5)
        
        if consecutive_errors >= max_consecutive_errors:
            print(f"Too many consecutive errors ({consecutive_errors}), waiting 30 seconds...")
            telegram_session = requests.Session()
            telegram_session.headers.update({"Connection": "keep-alive"})
            time.sleep(30)
            consecutive_errors = 0

if __name__ == "__main__":
    print("=" * 50)
    print("Hair Appointment Bot Starting...")
    print(f"Check interval: {CHECK_INTERVAL} seconds")
    print(f"Rate limit: {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW} seconds")
    print(f"One-liners loaded: {len(HAIRCUT_ADVICE)}")
    print("Using PERSISTENT REPLY KEYBOARD")
    print("=" * 50)
    
    print("Starting Flask server...")
    server_thread = Thread(target=run_http_server, daemon=False)
    server_thread.start()
    
    time.sleep(3)
    print("Flask server should be running now")
    
    print("Starting automated check loop...")
    check_thread = Thread(target=automated_check_loop, daemon=True)
    check_thread.start()
    
    print("Starting Telegram bot...")
    handle_telegram_updates()
