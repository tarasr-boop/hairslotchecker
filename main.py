import requests
import os
import datetime
import time
import re
from collections import defaultdict

# --- CONFIGURATION ---
BOT_TOKEN = os.environ['TELEGRAM_TOKEN']
RECIPIENT_IDS = [
    os.environ['TELEGRAM_CHAT_ID_TARAS'],
    os.environ['TELEGRAM_CHAT_ID_SOFIIA']
]

BUSINESS_ID = "8ab07528-c2a9-463d-a441-3e0aa39a975e"
STAFF_ID = "339008" 

SERVICES_TO_CHECK = {
    "Short hair (1 hour)": "1802687:SV", 
    "Long hair (1.5 hours)": "1802702:SV"
}

# --- SESSION SETUP ---
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Origin": "https://book.gettimely.com",
    "Referer": f"https://book.gettimely.com/Booking/Service?obg={BUSINESS_ID}",
    "X-Requested-With": "XMLHttpRequest"
})

def send_notification(message):
    """Send Telegram notification to all recipients."""
    for chat_id in RECIPIENT_IDS:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Msg fail: {e}")
            return False

def check_for_commands():
    """Check if user sent a command via Telegram and respond."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if not data.get('ok'):
            return False
        
        updates = data.get('result', [])
        if not updates:
            return False
        
        # Get the latest message
        latest_update = updates[-1]
        message = latest_update.get('message', {})
        text = message.get('text', '').strip().lower()
        chat_id = message.get('chat', {}).get('id')
        
        # Only respond to authorized users
        if str(chat_id) not in RECIPIENT_IDS:
            return False
        
        # Handle commands
        if text in ['/status', 'status', '/check', 'check']:
            status_msg = f"✅ <b>Bot Status</b>\n\n"
            status_msg += f"🤖 Bot is running normally\n"
            status_msg += f"🕐 Last check: {datetime.datetime.now().strftime('%d %B %Y at %I:%M %p')}\n"
            status_msg += f"📅 Checking next 30 days\n\n"
            status_msg += f"<i>Automated checks run every 10 minutes</i>"
            
            send_notification(status_msg)
            
            # Mark message as read by updating offset
            update_id = latest_update.get('update_id')
            requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={update_id + 1}", timeout=5)
            
            return True
        
        elif text in ['/checknow', 'check now', 'now']:
            send_notification("🔍 <b>Manual Check Started</b>\n\nChecking for available slots...")
            return 'run_check'
        
    except Exception as e:
        print(f"Command check error: {e}")
    
    return False

def set_service_session(service_id):
    """
    Sends the POST request to 'lock' the specific service into the session.
    """
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
    """
    Convert time string like '11:00AM' or '2:30PM' to minutes since midnight.
    Used for sorting and filtering consecutive slots.
    """
    time_str = time_str.upper().replace(" ", "")
    match = re.match(r'(\d{1,2}):(\d{2})(AM|PM)', time_str)
    if not match:
        return None
    
    hours = int(match.group(1))
    minutes = int(match.group(2))
    period = match.group(3)
    
    # Convert to 24-hour format
    if period == 'PM' and hours != 12:
        hours += 12
    elif period == 'AM' and hours == 12:
        hours = 0
    
    return hours * 60 + minutes

def get_specific_times(date_str):
    """
    Fetch available time slots for a specific date.
    Returns only the first time slot (actual appointment start time).
    """
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
        
        # Normalise times: remove spaces and convert to uppercase
        normalised_times = [t.replace(" ", "").upper() for t in times]
        unique_times = sorted(list(set(normalised_times)), key=parse_time_to_minutes)
        
        # Return only the first time slot (the actual appointment start time)
        if unique_times:
            return unique_times[0]
        return "No fitting slots"
    except Exception as e:
        print(f"Error fetching times for {date_str}: {e}")
        return "Time unknown"

def check_service_month(year, month):
    """
    Check which dates are available for booking in a given month.
    Returns list of date strings in format 'YYYY-MM-DD'.
    """
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

def is_status_check():
    """
    Determine if this is a status check run (daily at 7 PM).
    We check if the current hour is 19 (7 PM).
    """
    # Get environment variable to force status check (for testing)
    force_status = os.environ.get('FORCE_STATUS_CHECK', 'false').lower() == 'true'
    
    if force_status:
        return True
    
    # Check if it's 7 PM
    now = datetime.datetime.now()
    return now.hour == 19

def run_checks():
    """Main function to check availability for all services."""
    print("--- Starting Session Check ---")
    
    # First, check for any commands
    command_result = check_for_commands()
    if command_result == True:
        print("Status command received and responded to")
        return
    # If command_result is 'run_check', continue with the check
    
    today = datetime.date.today()
    cutoff_date = today + datetime.timedelta(days=30)
    
    status_check = is_status_check()
    
    print(f"Today: {today}")
    print(f"Checking next 30 days until: {cutoff_date}")
    print(f"Status check mode: {status_check}")
    
    results = defaultdict(list)
    found_any_slots = False
    
    # Determine which months to check (current month + next month to cover 30 days)
    months_to_check = []
    current_month = today.month
    current_year = today.year
    
    months_to_check.append((current_year, current_month))
    
    # Add next month
    next_month = current_month + 1
    next_year = current_year
    if next_month > 12:
        next_month = 1
        next_year += 1
    months_to_check.append((next_year, next_month))
    
    # Iterate through both services
    for service_name, service_id in SERVICES_TO_CHECK.items():
        print(f"\n🔎 Checking {service_name}...")
        
        # Clear cookies to ensure clean state
        session.cookies.clear()
        
        # Set the service session
        if not set_service_session(service_id):
            print(f"   ⚠️ Failed to set session for {service_name}. Skipping...")
            continue

        # Check the months
        for year, month in months_to_check:
            dates = check_service_month(year, month)
            
            if dates:
                print(f"   Found {len(dates)} days in {datetime.date(year, month, 1).strftime('%B')}")
                
                for d_str in dates:
                    d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
                    
                    # ONLY process dates within the next 30 days
                    if d_obj < today or d_obj > cutoff_date:
                        continue
                    
                    time_str = get_specific_times(d_str)
                    
                    if time_str == "No fitting slots":
                        continue

                    found_any_slots = True
                    nice_date = d_obj.strftime("%d %B")
                    entry = f"• {nice_date}: {time_str}"
                    results[service_name].append(entry)
                    
                    time.sleep(0.5)
        
        time.sleep(1)

    # Send notification based on findings and whether it's a status check
    if found_any_slots:
        # --- SLOTS FOUND MESSAGE ---
        final_msg = "🚨 <b>Update</b>\n"
        
        for service_name, entries in results.items():
            if entries:
                final_msg += f"\n➖➖➖➖➖➖➖➖➖➖\n<b>{service_name}</b>\n"
                final_msg += "\n".join(entries) + "\n"

        final_msg += "\n🔗 <a href='https://bookings.gettimely.com/hairbytaras/book'>Click to Book Now</a>"
        
        send_notification(final_msg)
        print("✅ Slots found! Notification sent!")
        
    elif status_check:
        # --- DAILY STATUS MESSAGE (no slots found) ---
        status_msg = f"✅ <b>Daily Status Check</b>\n\n"
        status_msg += f"Script is running normally.\n"
        status_msg += f"No appointments available in the next 30 days.\n\n"
        status_msg += f"<i>Checked: {datetime.datetime.now().strftime('%d %B %Y at %I:%M %p')}</i>"
        
        send_notification(status_msg)
        print("✅ Daily status check sent (no slots found)")
        
    else:
        # Regular check with no slots - stay silent
        print("❌ No slots available in next 30 days. No notification sent (not status check time).")

if __name__ == "__main__":
    run_checks()
