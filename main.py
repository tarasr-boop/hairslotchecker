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
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Msg fail: {e}")

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

def should_skip_april(month_name):
    """Check if the month is April (to be skipped)."""
    return month_name == "April"

def run_checks():
    """Main function to check availability for all services."""
    print("--- Starting Session Check ---")
    today = datetime.date.today()
    
    results = defaultdict(lambda: defaultdict(list))
    
    # Iterate through both services
    for service_name, service_id in SERVICES_TO_CHECK.items():
        print(f"\n🔎 Checking {service_name}...")
        
        # Clear cookies to ensure clean state
        session.cookies.clear()
        
        # Set the service session
        if not set_service_session(service_id):
            print(f"   ⚠️ Failed to set session for {service_name}. Skipping...")
            continue

        # Check today + next 2 months (total 3 months)
        for i in range(3): 
            target_month = today.month + i
            target_year = today.year
            if target_month > 12:
                target_month -= 12
                target_year += 1
            
            dummy_date = datetime.date(target_year, target_month, 1)
            month_name = dummy_date.strftime("%B")

            # Skip April
            if should_skip_april(month_name):
                continue

            # Check available dates
            dates = check_service_month(target_year, target_month)
            
            if dates:
                print(f"   Found {len(dates)} days in {month_name}")
                month_has_valid_slots = False
                
                for d_str in dates:
                    d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d")
                    
                    # Skip April dates (spillover check)
                    if d_obj.month == 4:
                        continue

                    time_str = get_specific_times(d_str)
                    
                    if time_str == "No fitting slots":
                        continue

                    month_has_valid_slots = True
                    nice_date = d_obj.strftime("%d %B")
                    entry = f"• {nice_date}: {time_str}"
                    
                    actual_month_name = d_obj.strftime("%B")
                    if not should_skip_april(actual_month_name):
                        results[service_name][actual_month_name].append(entry)
                    
                    time.sleep(0.5)
                
                # If we found dates but none had fitting slots, mark as Nothing
                if not month_has_valid_slots:
                    if not should_skip_april(month_name):
                        results[service_name][month_name].append("Nothing")
            else:
                # API returned no dates at all
                if not should_skip_april(month_name):
                    results[service_name][month_name].append("Nothing")
        
        time.sleep(1)

    # --- FINAL MESSAGE CONSTRUCTION ---
    final_msg = "🚨 <b>Update</b>\n"
    
    for service, months_data in results.items():
        final_msg += f"\n➖➖➖➖➖➖➖➖➖➖\n<b>{service}</b>\n"
        for month, entries in months_data.items():
            if should_skip_april(month):
                continue
            
            if entries:
                final_msg += f"\n📅 <b>{month}:</b>\n" + "\n".join(entries) + "\n"

    final_msg += "\n🔗 <a href='https://bookings.gettimely.com/hairbytaras/book'>Click to Book Now</a>"
    
    # Send notification always (to confirm the scheduler is running)
    send_notification(final_msg)
    print("Notification sent!")

if __name__ == "__main__":
    run_checks()
