import requests
import os
import datetime
import time
import re
from collections import defaultdict
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
BOT_TOKEN = os.environ['TELEGRAM_TOKEN']
RECIPIENT_IDS = [
    os.environ['TELEGRAM_CHAT_ID_TARAS'],
    os.environ['TELEGRAM_CHAT_ID_SOFIIA']
]

BUSINESS_ID = "8ab07528-c2a9-463d-a441-3e0aa39a975e"
STAFF_ID = "339008" 

SERVICES_TO_CHECK = {
    "💇‍♂️ Short hair (1 hour)": "1802687", 
    "🦁 Curly hair (1.5 hours)": "1802702"
}

def send_notification(message):
    for chat_id in RECIPIENT_IDS:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
            requests.post(url, json=payload)
        except Exception as e:
            print(f"Msg fail: {e}")

def get_specific_times(date_str, service_id):
    """
    Hits the specific endpoint to get hours for a single day.
    Returns a string like "11:00am, 2:30pm"
    """
    url = "https://book.gettimely.com/booking/gettimeslots"
    params = {
        "obg": BUSINESS_ID,
        "dateSelected": date_str,
        "staffId": STAFF_ID,
        "serviceIds": service_id, # We assume they need this to calc duration
        "tzId": "57"
    }
    # Headers mimicking your browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        # This endpoint returns HTML, not JSON. We use Regex to find times quickly.
        # It looks for patterns like "11:00am" or "1:30pm"
        times = re.findall(r'\d{1,2}:\d{2}(?:am|pm)', response.text)
        
        # Remove duplicates and sort
        unique_times = sorted(list(set(times)))
        
        if unique_times:
            return ", ".join(unique_times)
        return "Check link for times"
        
    except Exception as e:
        print(f"Error getting times for {date_str}: {e}")
        return "Time unknown"

def check_service_month(year, month, service_id):
    url = "https://book.gettimely.com/Booking/GetOpenDates"
    params = {
        "obg": BUSINESS_ID,
        "month": month,
        "year": year,
        "staffId": STAFF_ID,
        "serviceIds": service_id, 
        "tzId": "57"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()
        
        found_dates = []
        if isinstance(data, dict) and "openDates" in data:
            for item in data["openDates"]:
                if "day" in item:
                    found_dates.append(item["day"])
        return found_dates
    except Exception as e:
        print(f"Error checking {year}-{month}: {e}")
        return []

def run_checks():
    print("--- Starting Check ---")
    today = datetime.date.today()
    
    # Store results: results["Short Hair"]["February"] = ["18 Feb (11:00am)", ...]
    results = defaultdict(lambda: defaultdict(list))
    has_found_any = False

    for service_name, service_id in SERVICES_TO_CHECK.items():
        print(f"\n🔎 Checking {service_name}...")
        
        for i in range(4): 
            target_month = today.month + i
            target_year = today.year
            if target_month > 12:
                target_month -= 12
                target_year += 1

            dates = check_service_month(target_year, target_month, service_id)
            
            if dates:
                has_found_any = True
                print(f"   Found {len(dates)} days in {target_month}/{target_year}")
                
                for d_str in dates:
                    # 1. Get the specific times for this day
                    time_str = get_specific_times(d_str, service_id)
                    
                    # 2. Format the date
                    d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d")
                    month_name = d_obj.strftime("%B")
                    nice_date = d_obj.strftime("%d %B")
                    
                    # 3. Save it: "18 February: 11:00am, 2:00pm"
                    entry = f"• {nice_date}: {time_str}"
                    results[service_name][month_name].append(entry)
                    
                    # Sleep slightly to avoid spamming the "Time" endpoint
                    time.sleep(0.5)
        
        time.sleep(1)

    if has_found_any:
        final_msg = "🚨 <b>HAIR BY TARAS UPDATE</b>\n"
        
        for service, months_data in results.items():
            final_msg += f"\n➖➖➖➖➖➖➖➖➖➖\n"
            final_msg += f"<b>{service}</b>\n"
            
            for month, entries in months_data.items():
                final_msg += f"\n📅 <b>{month}:</b>\n"
                # Add the list of days+times
                final_msg += "\n".join(entries) + "\n"
        
        final_msg += "\n🔗 <a href='https://bookings.gettimely.com/hairbytaras/book'>Click to Book Now</a>"
        
        send_notification(final_msg)
        print("Notification sent!")
    else:
        print("\nNo dates found.")

if __name__ == "__main__":
    run_checks()
