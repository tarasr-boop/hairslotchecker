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

def get_specific_times(date_str):
    """
    Hits the specific endpoint to get hours for a single day.
    """
    url = "https://book.gettimely.com/booking/gettimeslots"
    params = {
        "obg": BUSINESS_ID,
        "dateSelected": date_str,
        "staffId": "-1",
        "tzId": "57"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        # Regex to find times like "11:00am", "11:00 am", "11:00 PM"
        # \s* allows for an optional space
        times = re.findall(r'\d{1,2}:\d{2}\s*(?:am|pm)', response.text, re.IGNORECASE)
        
        # Clean up (remove duplicates and sort)
        unique_times = sorted(list(set(times)))
        
        if unique_times:
            return ", ".join(unique_times)
        
        return "Check link"
        
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
    
    # Structure: results["Short Hair"]["February"] = ["• 18 Feb: 11:00am"]
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
            
            # Get the Month Name (e.g. "February") immediately
            dummy_date = datetime.date(target_year, target_month, 1)
            month_name = dummy_date.strftime("%B")

            dates = check_service_month(target_year, target_month, service_id)
            
            if dates:
                has_found_any = True
                print(f"   Found {len(dates)} days in {month_name}")
                
                for d_str in dates:
                    # 1. Get exact times
                    time_str = get_specific_times(d_str)
                    
                    # 2. Format nice date "18 Feb"
                    d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d")
                    nice_date = d_obj.strftime("%d %B")
                    
                    entry = f"• {nice_date}: {time_str}"
                    results[service_name][month_name].append(entry)
                    time.sleep(0.5)
            else:
                # Add explicit "Nothing" entry if no dates found
                results[service_name][month_name].append("Nothing")
        
        time.sleep(1)

    # Only send notification if AT LEAST ONE slot was found somewhere.
    # Otherwise, you would get a "Nothing" message every 5 minutes forever.
    if has_found_any:
        final_msg = "🚨 <b>HAIR BY TARAS UPDATE</b>\n"
        
        for service, months_data in results.items():
            final_msg += f"\n➖➖➖➖➖➖➖➖➖➖\n"
            final_msg += f"<b>{service}</b>\n"
            
            for month, entries in months_data.items():
                final_msg += f"\n📅 <b>{month}:</b>\n"
                # Join all entries (dates or "Nothing")
                final_msg += "\n".join(entries) + "\n"
        
        final_msg += "\n🔗 <a href='https://bookings.gettimely.com/hairbytaras/book'>Click to Book Now</a>"
        
        send_notification(final_msg)
        print("Notification sent!")
    else:
        print("\nNo dates found (Silence).")

if __name__ == "__main__":
    run_checks()
