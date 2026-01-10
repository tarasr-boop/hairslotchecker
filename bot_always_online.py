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
            
            # If we get here, request failed
            if attempt < retries - 1:
                time.sleep(2)
                continue
                
        except Exception as e:
            print(f"Error sending message (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2)
            
    return None
