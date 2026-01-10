import requests
import os
import datetime
import json
import time

# --- CONFIGURATION ---
BOT_TOKEN = os.environ['TELEGRAM_TOKEN']
RECIPIENT_IDS = [
    os.environ['TELEGRAM_CHAT_ID_TARAS'],
    os.environ['TELEGRAM_CHAT_ID_SOFIIA']
]

BUSINESS_ID = "8ab07528-c2a9-463d-a441-3e0aa39a975e"
STAFF_ID = "339008"  # This is Taras's specific ID found in your screenshot

# FIXED: Removed the ":SV" from the ends of these numbers
SERVICES_TO_CHECK = {
    "💇‍♂️ Short Hair Clipper": "1802687", 
    "🦁 Curly Cut": "1802702"
}

def send_notification(message):
    for chat_id in RECIPIENT_IDS:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": message})
        except:
            pass

def check_service_month(year, month, service_name, service_id):
    url = "https://book.gettimely.com/Booking/GetOpenDates"
    
    params = {
        "obg": BUSINESS_ID,
        "month": month,
        "year": year,
        "staffId": STAFF_ID, # Request Taras specifically
        "serviceIds": service_id, 
        "tzId": "57"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Referer": f"https://book.gettimely.com/Booking/StaffSelection?obg={BUSINESS_ID}",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()
        
        # DEBUG: This will print the site's reply to the GitHub logs
        # Look for this line if you get "No dates found" again!
        print(f"DEBUG {service_name} ({year}-{month}): {str(data)[:200]}")

        if isinstance(data, list): return data
        elif "startDates" in data: return data["startDates"]
        return []
    except Exception as e:
        print(f"Error checking {service_name} {year}-{month}: {e}")
        return []

def run_checks():
    print("--- Starting Multi-Service Check ---")
    today = datetime.date.today()
    found_messages = []

    for service_name, service_id in SERVICES_TO_CHECK.items():
        print(f"\n🔎 Checking {service_name}...")
        
        for i in range(4): 
            target_month = today.month + i
            target_year = today.year
            if target_month > 12:
                target_month -= 12
                target_year += 1

            dates = check_service_month(target_year, target_month, service_name, service_id)
            
            if dates:
                print(f"✅ FOUND: {len(dates)} slots in {target_month}/{target_year}")
                found_messages.append(f"✅ {service_name} ({target_month}/{target_year}):")
                found_messages.append(f"   Dates: {', '.join(dates[:5])}")
                if len(dates) > 5: found_messages.append("   ...and more!")
                found_messages.append("")
        
        time.sleep(1)

    if found_messages:
        final_msg = "🚨 HAIR BY TARAS UPDATES!\n\n" + "\n".join(found_messages)
        final_msg += "\nBook here: https://bookings.gettimely.com/hairbytaras/book"
        send_notification(final_msg)
    else:
        print("\nNo dates found for any service.")

if __name__ == "__main__":
    run_checks()
