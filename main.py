import requests
import os
import datetime
import time
import re
from collections import defaultdict
import pytz
import random

# --- CONFIGURATION ---
BOT_TOKEN = os.environ['TELEGRAM_TOKEN']

BUSINESS_ID = "8ab07528-c2a9-463d-a441-3e0aa39a975e"
STAFF_ID = "339008" 

SERVICES_TO_CHECK = {
    "Short hair (1 hour)": "1802687:SV", 
    "Long hair (1.5 hours)": "1802702:SV"
}

# Melbourne timezone
MELBOURNE_TZ = pytz.timezone('Australia/Melbourne')

# Funny haircut advice options
HAIRCUT_ADVICE = [
    "🚫 Absolutely not. Your hair is perfect. Don't you dare touch it.",
    "✂️ YES! Book it NOW! Your hair has been plotting against you.",
    "🤔 Ask again after you've had coffee. This is too big a decision.",
    "💇 Your hair called. It said 'please no, we had a good run.'",
    "🎲 Flip a coin. Heads = haircut, Tails = grow it to your ankles.",
    "🧠 According to my calculations, you have exactly 3 days before critical hair failure.",
    "🎭 Only if you're ready to commit to the post-haircut selfie.",
    "⏰ It's been [REDACTED] days. The answer is always yes.",
    "🌟 Your hair looks fine, but imagine how aerodynamic you could be.",
    "🎸 Real rockstars never get haircuts. Are you a rockstar?",
    "📅 Check the moon phase. Mercury is in retrograde. Proceed with caution.",
    "🐑 Only if you promise not to look like a freshly sheared sheep.",
    "💸 Yes, but only if you tip the barber in interpretive dance.",
    "🎪 Embrace the chaos. Get a mullet.",
    "🧙 The magic 8-ball says: 'Reply hazy, try again after shampooing.'",
    "🦁 You don't need a haircut. You need a safari hat.",
    "⚡ Yes! Strike while the scissors are hot!",
    "🎯 Absolutely not. Growing it out is your current life quest.",
    "🍕 Only if there's pizza involved afterwards. No pizza = no haircut.",
    "🎨 Your hair is a masterpiece in progress. Don't interrupt the artist."
]

# --- SESSION SETUP ---
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Origin": "https://book.gettimely.com",
    "Referer": f"https://book.gettimely.com/Booking/Service?obg={BUSINESS_ID}",
    "X-Requested-With": "XMLHttpRequest"
})

def get_melbourne_time():
    """Get current time in Melbourne timezone."""
    return datetime.datetime.now(MELBOURNE_TZ)

def send_telegram_message(chat_id, message, reply_markup=None):
    """Send message to specific chat."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id, 
            "text": message, 
            "parse_mode": "HTML"
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error sending message: {e}")
        return False

def send_menu(chat_id):
    """Send the main menu with inline keyboard buttons."""
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📊 Status", "callback_data": "status"},
                {"text": "🔍 Check Now", "callback_data": "checknow"}
            ],
            [
                {"text": "💇‍♂️ Should I Get a Haircut?", "callback_data": "haircut"}
            ]
        ]
    }
    
    message = "🤖 <b>Hair Appointment Bot</b>\n\nWhat would you like to do?"
    send_telegram_message(chat_id, message, reply_markup=keyboard)

def answer_callback(callback_query_id, text):
    """Answer a callback query (shows a popup notification)."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        payload = {
            "callback_query_id": callback_query_id,
            "text": text
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Error answering callback: {e}")

def set_service_session(service_id):
    """Sends the POST request to 'lock' the specific service into the session."""
    url = f"https://book.gettimely.com/Booking/Service?obg={BUSINESS_ID}"
    
    payload = {
        "OnlineBookingMultiServiceEnabled": "True",
        "LocationId": "0",
        f"ServiceStaffIds[{service_id}]": STAFF_ID,
        "BookableTimeSlotItemIds": service_id
    }
    
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        response = session.post(url, data=payload, headers=headers, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error setting service {service_id}: {e}")
        return False

def parse_time_to_minutes(time_str):
    """Convert time string to minutes since midnight."""
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
    """Fetch available time slots for a specific date."""
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
        return "No fitting slots"
    except Exception as e:
        print(f"Error fetching times for {date_str}: {e}")
        return "Time unknown"

def check_service_month(year, month):
    """Check which dates are available for booking in a given month."""
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
        print(f"Error checking month {year}-{month}: {e}")
        return []

def do_slot_check(full_check=False):
    """Perform the actual slot checking logic."""
    melbourne_time = get_melbourne_time()
    today = melbourne_time.date()
    
    print(f"Today (Melbourne): {today}")
    print(f"Full check mode: {full_check}")
    
    results = defaultdict(lambda: defaultdict(list))
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
        print(f"\n🔎 Checking {service_name}...")
        
        session.cookies.clear()
        
        if not set_service_session(service_id):
            print(f"   ⚠️ Failed to set session for {service_name}. Skipping...")
            continue

        for year, month in months_to_check:
            dates = check_service_month(year, month)
            
            if dates:
                month_name = datetime.date(year, month, 1).strftime('%B')
                print(f"   Found {len(dates)} days in {month_name}")
                
                for d_str in dates:
                    d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
                    
                    if full_check:
                        if d_obj.month != month:
                            continue
                    else:
                        if d_obj < today or d_obj > cutoff_date:
                            continue
                    
                    time_str = get_specific_times(d_str)
                    
                    if time_str == "No fitting slots":
                        continue

                    found_any_slots = True
                    nice_date = d_obj.strftime("%d %B")
                    entry = f"• {nice_date}: {time_str}"
                    
                    actual_month_name = d_obj.strftime("%B")
                    results[service_name][actual_month_name].append(entry)
                    
                    time.sleep(0.5)
        
        time.sleep(1)
    
    return found_any_slots, results

def handle_updates():
    """Handle all Telegram updates (messages and button presses)."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if not data.get('ok'):
            print("Failed to get updates")
            return
        
        updates = data.get('result', [])
        if not updates:
            print("No new updates")
            return
        
        # Process ALL unprocessed updates
        for update in updates:
            update_id = update.get('update_id')
            
            # Handle button presses (callback queries)
            if 'callback_query' in update:
                callback = update['callback_query']
                callback_data = callback.get('data', '')
                chat_id = callback['message']['chat']['id']
                callback_query_id = callback['id']
                
                print(f"Button pressed: {callback_data} by chat {chat_id}")
                
                if callback_data == 'status':
                    answer_callback(callback_query_id, "⏳ Getting status...")
                    
                    melbourne_time = get_melbourne_time()
                    status_msg = f"✅ <b>Bot Status</b>\n\n"
                    status_msg += f"🤖 Bot is running normally\n"
                    status_msg += f"🕐 Last check: {melbourne_time.strftime('%d %B %Y at %I:%M %p')}\n"
                    status_msg += f"📅 Checking next 30 days\n\n"
                    status_msg += f"<i>Automated checks run every 6 minutes</i>"
                    
                    send_telegram_message(chat_id, status_msg)
                    send_menu(chat_id)
                    
                elif callback_data == 'checknow':
                    answer_callback(callback_query_id, "🔍 Checking...")
                    send_telegram_message(chat_id, "🔍 <b>Checking next 3 months...</b>\n\n<i>Stand by, this may take a minute</i>")
                    
                    found_any_slots, results = do_slot_check(full_check=True)
                    
                    if found_any_slots:
                        final_msg = "🚨 <b>Update</b>\n"
                        
                        for service_name, months_data in results.items():
                            if months_data:
                                final_msg += f"\n➖➖➖➖➖➖➖➖➖➖\n<b>{service_name}</b>\n"
                                
                                for month_name, entries in months_data.items():
                                    final_msg += f"\n📅 <b>{month_name}:</b>\n"
                                    final_msg += "\n".join(entries) + "\n"

                        final_msg += "\n🔗 <a href='https://bookings.gettimely.com/hairbytaras/book'>Click to Book Now</a>"
                        send_telegram_message(chat_id, final_msg)
                    else:
                        send_telegram_message(chat_id, f"❌ <b>No Slots Available</b>\n\nNo appointments in next 3 months.\n\n<i>Checked: {get_melbourne_time().strftime('%d %B at %I:%M %p')}</i>")
                    
                    send_menu(chat_id)
                    
                elif callback_data == 'haircut':
                    answer_callback(callback_query_id, "🎱 Consulting the hair gods...")
                    advice = random.choice(HAIRCUT_ADVICE)
                    send_telegram_message(chat_id, f"💇‍♂️ <b>Should You Get a Haircut?</b>\n\n{advice}")
                    send_menu(chat_id)
            
            # Handle text messages
            elif 'message' in update:
                message = update['message']
                text = message.get('text', '').strip()
                chat_id = message['chat']['id']
                
                print(f"Message from {chat_id}: {text}")
                
                # Respond to any message with the menu
                send_menu(chat_id)
            
            # Mark this update as processed
            requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={update_id + 1}", timeout=5)
        
    except Exception as e:
        print(f"Error handling updates: {e}")

def is_status_check():
    """Check if it's 7 PM Melbourne time for daily status."""
    force_status = os.environ.get('FORCE_STATUS_CHECK', 'false').lower() == 'true'
    if force_status:
        return True
    
    melbourne_time = get_melbourne_time()
    return melbourne_time.hour == 19

def run_checks():
    """Main function."""
    print("--- Starting Check ---")
    
    # First, handle any Telegram commands/buttons
    handle_updates()
    
    # Then do scheduled checking
    status_check = is_status_check()
    found_any_slots, results = do_slot_check(full_check=False)
    
    # For scheduled checks, we need to broadcast to all known users
    # Since we removed user authentication, we'll skip broadcast notifications
    # and only respond to direct interactions
    
    if found_any_slots or status_check:
        print(f"Slots found: {found_any_slots}, Status check: {status_check}")
        # Note: You'd need to store chat_ids somewhere to broadcast
        # For now, users must interact with the bot to get updates
    else:
        print("No slots, not status time. Silent.")

if __name__ == "__main__":
    run_checks()
