import requests
import os
import datetime
import json

# --- CONFIGURATION ---
BOT_TOKEN = os.environ['TELEGRAM_TOKEN']
RECIPIENT_IDS = [
    os.environ['TELEGRAM_CHAT_ID_TARAS'],
    os.environ['TELEGRAM_CHAT_ID_SOFIIA']
]

# The unique ID for Hair By Taras from your link
BUSINESS_ID = "8ab07528-c2a9-463d-a441-3e0aa39a975e"

def send_notification(message):
    for chat_id in RECIPIENT_IDS:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": message})
            print(f"Sent to ...{str(chat_id)[-4:]}")
        except:
            pass

def check_month(year, month):
    """
    Hits the Timely API for a specific month/year.
    Returns a list of available dates.
    """
    url = "https://book.gettimely.com/Booking/GetOpenDates"
    
    # These match the parameters in your CURL command
    params = {
        "obg": BUSINESS_ID,
        "month": month,
        "year": year,
        "staffId": "-1",  # -1 usually means "Any Staff"
        "tzId": "57"      # Timezone ID from your link
    }

    # Headers from your CURL command (Simplified to avoid expiration issues)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Referer": f"https://book.gettimely.com/Booking/StaffSelection?obg={BUSINESS_ID}",
        "X-Requested-With": "XMLHttpRequest", # Crucial for telling them we are a script
        "Accept": "application/json, text/javascript, */*; q=0.01"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()
        
        # The API usually returns key "startDates" or just a list of dates
        # We look for any list that is not empty
        if isinstance(data, list):
            return data # It's a list of dates
        elif "startDates" in data:
            return data["startDates"]
        
        return []
        
    except Exception as e:
        print(f"Error checking {year}-{month}: {e}")
        return []

def run_checks():
    print("--- Starting API Check ---")
    
    # Get today's date
    today = datetime.date.today()
    
    # We want to check THIS month and NEXT month
    # (So if it's Jan 30, we also check Feb)
    months_to_check = [
        (today.year, today.month),
        (today.year, today.month + 1)
    ]
    
    found_dates = []

    for year, month in months_to_check:
        # Handle year rollover (if month is 13, make it Jan of next year)
        if month > 12:
            month = 1
            year += 1
            
        print(f"Checking {year}-{month}...")
        dates = check_month(year, month)
        
        if dates:
            print(f"FOUND DATES: {dates}")
            found_dates.extend(dates)
    
    if found_dates:
        # Format the message nicely
        msg = f"🚨 HAIR BY TARAS OPENINGS!\nFound {len(found_dates)} available days:\n" + "\n".join(found_dates[:5])
        if len(found_dates) > 5: 
            msg += "\n...and more!"
        msg += f"\n\nBook here: https://bookings.gettimely.com/hairbytaras/book"
        
        send_notification(msg)
    else:
        print("No dates found.")

if __name__ == "__main__":
    # FORCE A TEST MESSAGE
    send_notification("✅ TEST: The bot is working and connected!") 
    
    # Run the real check
    run_checks()
