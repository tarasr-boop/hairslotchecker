import requests
import os
import datetime
import time
import re
from collections import defaultdict
import pytz
import random
from threading import Thread
from flask import Flask # NEW IMPORT

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not BOT_TOKEN:
    raise Exception("TELEGRAM_TOKEN environment variable not set!")

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

# Global variables
active_chat_ids = set()
last_check_string = "Not checked yet" 

# Esoteric & Simple Haircut Advice
HAIRCUT_ADVICE = [
    "Absolutely not. Your hair is perfect. Don't you dare touch it.",
    "YES. Book it. Your hair has been plotting against you.",
    "Ask again after you've had coffee. This is too big a decision.",
    "Your hair called. It said 'please no, we had a good run.'",
    "Flip a coin. Heads is haircut, Tails is grow it to your ankles.",
    "According to calculations, you have exactly 3 days before critical hair failure.",
    "Only if you're ready to commit to the post-haircut selfie.",
    "It has been too long. The answer is yes.",
    "Your hair looks fine, but imagine how aerodynamic you could be.",
    "Real rockstars never get haircuts. Are you a rockstar?",
    "Check the moon phase. Mercury is in retrograde. Proceed with caution.",
    "Only if you promise not to look like a freshly sheared sheep.",
    "Yes, but only if you tip the barber in interpretive dance.",
    "Embrace the chaos. Get a mullet.",
    "The magic 8-ball says: 'Reply hazy, try again after shampooing.'",
    "You don't need a haircut. You need a safari hat.",
    "Yes. Strike while the scissors are hot.",
    "Absolutely not. Growing it out is your current life quest.",
    "Only if there's pizza involved afterwards. No pizza = no haircut.",
    "Your hair is a masterpiece in progress. Don't interrupt the artist.",
    "The void whispers 'trim'. Do not ignore the void.",
    "Your aura is tangled. A haircut is the only spiritual detangler.",
    "Entropy increases as your hair grows. Reverse the flow.",
    "The scissors of destiny await your signal.",
    "Vibrationally, you are too heavy. Shed the weight.",
    "The ancient texts remain silent on your bangs.",
    "Do not disturb the natural decay of the universe.",
    "A haircut is a ritual of sacrifice. Are you prepared?",
    "The geometry of your current style offends the cosmos.",
    "Align your physical form with your astral projection. Cut it."
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

# --- FLASK SERVER TO KEEP RENDER ALIVE ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive"

def run_http_server():
    # Render assigns a port in the environment variable 'PORT'
    # We must listen on 0.0.0.0
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ------------------------------------------

def get_melbourne_time():
    """Get current time in Melbourne timezone."""
    return datetime.datetime.now(MELBOURNE_TZ)

def update_last_check_time():
    """Updates the global variable with current Melbourne time."""
    global last_check_string
    t = get_melbourne_time()
    last_check_string = t.strftime('%I:%M %p')

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
    """Send simple menu with 3 buttons."""
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📊 bot status", "callback_data": "status"},
                {"text": "🔍 check now", "callback_data": "checknow"}
            ],
            [
                {"text": "✂️ should i get a haircut?", "callback_data": "haircut"}
            ]
        ]
    }
    
    message = "What brings you here today?"
    send_message(chat_id, message, reply_markup=keyboard)

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
    # Timely needs this specific format for array parameters
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
    melbourne_time = get_melbourne_time()
    today = melbourne_time.date()
    
    results = defaultdict(lambda: defaultdict(list))
    found_any_slots = False
    
    months_to_check = []
    current_month = today.month
    current_year = today.year
    
    if full_check:
        # Check 3 months
        for i in range(3):
            target_month = current_month + i
            target_year = current_year
            if target_month > 12:
                target_month -= 12
                target_year += 1
            months_to_check.append((target_year, target_month))
    else:
        # Check 30 days
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
                    # Short month name format: "18 Feb"
                    nice_date = d_obj.strftime("%d %b")
                    entry = f"• {nice_date}: {time_str}"
                    
                    # Short month name for grouping
                    actual_month_name = d_obj.strftime("%b")
                    results[service_name][actual_month_name].append(entry)
                    
                    time.sleep(0.3)
        
        time.sleep(0.5)
    
    # Update global check time
    update_last_check_time()

    return found_any_slots, results

def format_results_simple(results):
    """Format results simply without emojis."""
    final_msg = "Updates found:\n"
    
    for service_name, months_data in results.items():
        if months_data:
            final_msg += f"\n-- {service_name} --\n"
            
            for month_name, entries in months_data.items():
                final_msg += f"\n{month_name}:\n"
                final_msg += "\n".join(entries) + "\n"

    final_msg += "\n<a href='https://bookings.gettimely.com/hairbytaras/book'>Book here</a>"
    return final_msg

def broadcast_to_users(message):
    """Send message to all active users."""
    for chat_id in list(active_chat_ids):
        send_message(chat_id, message)

def automated_check_loop():
    """Background thread that checks every 2 minutes."""
    print("Starting automated check loop (every 2 minutes)...")
    last_slots_found = False
    
    while True:
        try:
            print(f"\n--- Automated Check at {get_melbourne_time().strftime('%I:%M %p')} ---")
            
            found_any_slots, results = do_slot_check(full_check=False)
            
            # Only notify if slots are found AND it's a change from last check
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
                status_msg = f"Daily Report: Bot running. Last check: {last_check_string}"
                broadcast_to_users(status_msg)
            
        except Exception as e:
            print(f"Error in automated check: {e}")
        
        time.sleep(CHECK_INTERVAL)

def handle_telegram_updates():
    """Main bot loop - handles messages and button presses."""
    print("Starting Telegram bot...")
    offset = None
    
    # Start automated checking in background
    check_thread = Thread(target=automated_check_loop, daemon=True)
    check_thread.start()

    # --- START FLASK SERVER IN BACKGROUND ---
    server_thread = Thread(target=run_http_server, daemon=True)
    server_thread.start()
    # ----------------------------------------
    
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
                    
                    active_chat_ids.add(chat_id)
                    
                    if callback_data == 'status':
                        answer_callback(callback_query_id, "Getting status...")
                        
                        # Status report matching your format
                        status_msg = f"""✅ Bot Status

🤖 Running normally
🕐 Last time updated: {last_check_string}
📅 Checking next 30 days

Active users: {len(active_chat_ids)}"""
                        send_message(chat_id, status_msg)
                        send_menu(chat_id)
                        
                    elif callback_data == 'checknow':
                        answer_callback(callback_query_id, "Checking...")
                        send_message(chat_id, "Checking next 3 months...")
                        
                        found_any_slots, results = do_slot_check(full_check=True)
                        
                        if found_any_slots:
                            message = format_results_simple(results)
                            send_message(chat_id, message)
                        else:
                            # Simple no slots message
                            send_message(chat_id, "No slots found in next 3 months.")
                        
                        send_menu(chat_id)
                        
                    elif callback_data == 'haircut':
                        answer_callback(callback_query_id, "Consulting...")
                        advice = random.choice(HAIRCUT_ADVICE)
                        # Just the advice, no title
                        send_message(chat_id, advice)
                        send_menu(chat_id)
                
                # Handle text messages
                elif 'message' in update:
                    message = update['message']
                    chat_id = message['chat']['id']
                    
                    active_chat_ids.add(chat_id)
                    send_menu(chat_id)
        
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    print("Bot Starting...")
    print(f"Checking every {CHECK_INTERVAL} seconds")
    handle_telegram_updates()
