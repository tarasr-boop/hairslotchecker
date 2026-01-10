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

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not BOT_TOKEN:
    raise Exception("TELEGRAM_TOKEN environment variable not set!")

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

# Rate limiting: max 10 requests per minute per user
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW = 60  # seconds

# File to persist active users
USERS_FILE = "active_users.json"

# Global variables
active_chat_ids = set()
authenticated_users = set()  # Users who have entered the password
last_check_string = "Not checked yet"
last_slot_found_time = None  # Track when slots were last found
user_request_times = defaultdict(list)  # For rate limiting
rate_limit_lock = Lock()

# Esoteric & Witty Consulting-Themed Haircut Advice
HAIRCUT_ADVICE = [
    "Per my last email, your hair requires immediate strategic intervention.",
    "Let's take this offline—your split ends need a private consultation.",
    "I'll need to loop in the scissors on this one.",
    "Your hair's ROI is diminishing. Time to pivot.",
    "Let's circle back when your roots aren't showing.",
    "This is a high-priority follicle situation. Escalate immediately.",
    "Your current style lacks synergy. Consider a trim.",
    "We need to align your hair with Q4 objectives.",
    "I'm seeing some bandwidth issues with your current length.",
    "Let's table the haircut discussion until Mercury exits retrograde.",
    "Your hair is giving 'scope creep.' Rein it in.",
    "The deliverables are clear: you need a cut.",
    "I've done the due diligence. The recommendation is: scissors.",
    "Your hair has exceeded its sprint capacity. Time to groom the backlog.",
    "This requires a paradigm shift. From long to short.",
    "Let's not boil the ocean—just trim the ends.",
    "Your follicles are misaligned with stakeholder expectations.",
    "The optics on your current hairstyle are... suboptimal.",
    "We need to rightsize your hair situation.",
    "Your style lacks vertical integration. Consider layers.",
    "The ancient scrolls are silent on your bangs, but the consultants aren't.",
    "Your hair's burn rate is unsustainable. Cut costs. Literally.",
    "I'm flagging this as a blocker. The blocker is your hair.",
    "Let's leverage our core competencies here: booking appointments.",
    "Your hair is technically debt. Time to refactor.",
    "The tea leaves say 'trim.' The Gantt chart agrees.",
    "You're one haircut away from thought leadership.",
    "Your current aesthetic is not best practice.",
    "I've benchmarked your hair against industry standards. It's lagging.",
    "This is a change management issue. The change is: shorter hair.",
    "Your hair needs a retrospective. What went wrong?",
    "The oracle has been consulted. It invoiced you and said 'yes, cut it.'",
    "Strategically speaking, your hair is a liability.",
    "Let's not reinvent the wheel—just get a classic cut.",
    "Your hair is in technical debt. Time to pay it down.",
    "The consultants recommend a full restructuring. Starting with your head.",
    "Your style is legacy code. Time for a modern framework.",
    "I've run the numbers. The numbers say 'barber.'",
    "Your hair is not scalable in its current form.",
    "This is a quick win. Low effort, high impact: haircut.",
    "The SWOT analysis is complete. Your hair is a weakness.",
    "Let's action this: book the appointment.",
    "Your hair is not aligned with the north star metric.",
    "I'm seeing diminishing returns on your current length.",
    "The stakeholders have spoken. They want you trimmed.",
    "Your hair lacks a clear value proposition.",
    "Time to sunset your current hairstyle.",
    "The data doesn't lie. Your hair is overdue.",
    "Let's move the needle here. The needle is scissors.",
    "Your follicular strategy needs a complete overhaul."
]

# Session for appointment checking
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Origin": "https://book.gettimely.com",
    "Referer": f"https://book.gettimely.com/Booking/Service?obg={BUSINESS_ID}",
    "X-Requested-With": "XMLHttpRequest"
})

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
app = Flask('')

@app.route('/')
def home():
    return "I am alive"

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- RATE LIMITING ---
def check_rate_limit(chat_id):
    """Check if user is within rate limit. Returns True if allowed, False if rate limited."""
    with rate_limit_lock:
        now = time.time()
        # Clean old requests
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

# ------------------------------------------

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

def send_message(chat_id, text, reply_markup=None):
    """Send message to a specific chat."""
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
        return response.status_code == 200
    except Exception as e:
        print(f"Error sending message: {e}")
        return False

def send_menu(chat_id):
    """Send simple menu with buttons."""
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📊 bot status", "callback_data": "status"},
                {"text": "🔍 check now", "callback_data": "checknow"}
            ],
            [
                {"text": "✂️ should i get a haircut?", "callback_data": "haircut"}
            ],
            [
                {"text": "🔕 stop notifications", "callback_data": "stop_notifications"}
            ]
        ]
    }
    
    message = "What brings you here today?"
    send_message(chat_id, message, reply_markup=keyboard)

def send_welcome_message(chat_id):
    """Send welcome message with bot introduction after authentication."""
    intro = """✅ Authentication successful!

Welcome to the <b>Hair Appointment Bot</b> ✂️

<b>How it works:</b>
- I automatically check the booking website every 2 minutes
- If a slot becomes available, I'll send you a notification immediately
- If nothing is found, I stay quiet (no spam!)

<b>Manual options below:</b>
- Check status to see if I'm running
- Check now to manually search for slots

Let's find you an appointment!"""
    
    send_message(chat_id, intro)

def send_password_prompt(chat_id):
    """Send password prompt to unauthenticated user."""
    message = "🔐 This bot requires authentication.\n\nPlease enter the password to continue:"
    send_message(chat_id, message)

def answer_callback(callback_query_id, text):
    """Answer a callback query."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        payload = {"callback_query_id": callback_query_id, "text": text}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Error answering callback: {e}")

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
    
    # Structure: {service_name: [(date_obj, time_str), ...]}
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
    
    # Update global check time
    update_last_check_time()
    
    # Update last slot found time if we found slots
    if found_any_slots:
        last_slot_found_time = get_melbourne_time()

    return found_any_slots, results

def format_results_simple(results):
    """Format results in the new simple format without month grouping."""
    final_msg = "Updates found:\n"
    
    for service_name, slots in results.items():
        if slots:
            final_msg += f"\n{service_name}\n\n"
            
            # Sort by date
            sorted_slots = sorted(slots, key=lambda x: x[0])
            
            for date_obj, time_str in sorted_slots:
                # Full month name: "18 February"
                nice_date = f"{date_obj.day} {date_obj.strftime('%B')}"
                final_msg += f"• {nice_date}: {time_str}\n"

    final_msg += "\n<a href='https://bookings.gettimely.com/hairbytaras/book'>Book here</a>"
    return final_msg

def broadcast_to_users(message):
    """Send message to all active authenticated users."""
    for chat_id in list(active_chat_ids):
        if chat_id in authenticated_users:
            send_message(chat_id, message)

def notify_restart():
    """Notify users that the bot has restarted."""
    restart_msg = "🔄 Bot has restarted and is now running!\n\nYou will continue to receive notifications for available slots."
    for chat_id in list(active_chat_ids):
        if chat_id in authenticated_users:
            send_message(chat_id, restart_msg)

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
                print("Slots still available (no notification)")
            
            # Daily status at 7 PM
            melbourne_time = get_melbourne_time()
            if melbourne_time.hour == 19 and melbourne_time.minute < 2:
                status_msg = f"📊 Daily Report\n\n🤖 Bot running normally\n🕐 Last check: {last_check_string}"
                broadcast_to_users(status_msg)
            
            # Save users periodically
            save_users()
            
        except Exception as e:
            print(f"Error in automated check: {e}")
        
        time.sleep(CHECK_INTERVAL)

def handle_telegram_updates():
    """Main bot loop - handles messages and button presses."""
    print("Starting Telegram bot...")
    
    # Load persisted users
    load_users()
    
    # Notify users about restart
    if active_chat_ids:
        print("Notifying users about restart...")
        notify_restart()
    
    offset = None
    
    # Start automated checking in background
    check_thread = Thread(target=automated_check_loop, daemon=True)
    check_thread.start()

    # Start Flask server in background
    server_thread = Thread(target=run_http_server, daemon=True)
    server_thread.start()
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            
            response = requests.get(url, params=params, timeout=35)
            data = response.json()
            
            if not data.get('ok'):
                print("Error getting updates")
                time.sleep(5)
                continue
            
            updates = data.get('result', [])
            
            for update in updates:
                offset = update['update_id'] + 1
                
                # Handle button presses
                if 'callback_query' in update:
                    callback = update['callback_query']
                    callback_data = callback.get('data', '')
                    chat_id = callback['message']['chat']['id']
                    callback_query_id = callback['id']
                    
                    # Check if user is authenticated
                    if chat_id not in authenticated_users:
                        answer_callback(callback_query_id, "Please authenticate first!")
                        send_password_prompt(chat_id)
                        continue
                    
                    # Rate limiting check
                    if not check_rate_limit(chat_id):
                        answer_callback(callback_query_id, "Rate limited! Please wait.")
                        remaining_wait = RATE_LIMIT_WINDOW - (time.time() - min(user_request_times[chat_id]))
                        send_message(chat_id, f"⚠️ Rate limited! Please wait {int(remaining_wait)} seconds before making more requests.\n\nLimit: {RATE_LIMIT_REQUESTS} requests per minute.")
                        continue
                    
                    active_chat_ids.add(chat_id)
                    
                    if callback_data == 'status':
                        answer_callback(callback_query_id, "Getting status...")
                        
                        status_msg = f"""✅ Bot Status

🤖 Running normally
🕐 Last check: {last_check_string}
📅 Checking next 30 days

👥 Active users: {len(active_chat_ids)}
🔢 Your requests remaining: {get_rate_limit_remaining(chat_id)}/{RATE_LIMIT_REQUESTS} per minute"""
                        send_message(chat_id, status_msg)
                        send_menu(chat_id)
                        
                    elif callback_data == 'checknow':
                        answer_callback(callback_query_id, "Checking...")
                        send_message(chat_id, "🔍 Checking next 3 months...")
                        
                        found_any_slots, results = do_slot_check(full_check=True)
                        
                        if found_any_slots:
                            message = format_results_simple(results)
                            send_message(chat_id, message)
                        else:
                            send_message(chat_id, "❌ No slots found in next 3 months.")
                        
                        send_menu(chat_id)
                        
                    elif callback_data == 'haircut':
                        answer_callback(callback_query_id, "Thinking...")
                        advice = random.choice(HAIRCUT_ADVICE)
                        send_message(chat_id, advice)
                        send_menu(chat_id)
                    
                    elif callback_data == 'stop_notifications':
                        answer_callback(callback_query_id, "Notifications stopped")
                        active_chat_ids.discard(chat_id)
                        save_users()
                        send_message(chat_id, "🔕 You have been unsubscribed from notifications.\n\nYou will no longer receive automatic updates about available slots.\n\nSend any message to re-subscribe.")
                
                # Handle text messages
                elif 'message' in update:
                    message = update['message']
                    chat_id = message['chat']['id']
                    text = message.get('text', '').strip()
                    
                    # Check if user needs to authenticate
                    if chat_id not in authenticated_users:
                        if text.lower() == BOT_PASSWORD.lower():
                            authenticated_users.add(chat_id)
                            active_chat_ids.add(chat_id)
                            save_users()
                            send_welcome_message(chat_id)
                            send_menu(chat_id)
                        else:
                            send_password_prompt(chat_id)
                        continue
                    
                    # Rate limiting check
                    if not check_rate_limit(chat_id):
                        send_message(chat_id, f"⚠️ Rate limited! Please wait before making more requests.\n\nLimit: {RATE_LIMIT_REQUESTS} requests per minute.")
                        continue
                    
                    # User is authenticated, add to active and show menu
                    active_chat_ids.add(chat_id)
                    save_users()
                    send_menu(chat_id)
        
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    print("Bot Starting...")
    print(f"Checking every {CHECK_INTERVAL} seconds")
    handle_telegram_updates()
