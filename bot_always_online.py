# Add this near the top with other global variables (after last_menu_message_id)
chat_message_history = defaultdict(list)  # Track all message IDs per chat
MAX_MESSAGES_TO_KEEP = 2  # Keep only last 2 messages

# Replace the delete_previous_menu function with this enhanced version:
def cleanup_chat_messages(chat_id, new_message_id=None):
    """Delete old messages, keeping only the last MAX_MESSAGES_TO_KEEP messages."""
    try:
        # Add new message to history if provided
        if new_message_id:
            chat_message_history[chat_id].append(new_message_id)
        
        # If we have more than MAX_MESSAGES_TO_KEEP, delete the old ones
        while len(chat_message_history[chat_id]) > MAX_MESSAGES_TO_KEEP:
            old_message_id = chat_message_history[chat_id].pop(0)
            delete_message(chat_id, old_message_id)
            time.sleep(0.1)  # Small delay to avoid hitting rate limits
            
    except Exception as e:
        print(f"Error cleaning up messages: {e}")

def delete_previous_menu(chat_id):
    """Delete the previous menu message if it exists."""
    if chat_id in last_menu_message_id:
        delete_message(chat_id, last_menu_message_id[chat_id])
        # Also remove from history
        if last_menu_message_id[chat_id] in chat_message_history[chat_id]:
            chat_message_history[chat_id].remove(last_menu_message_id[chat_id])
        del last_menu_message_id[chat_id]

# Update send_message to track messages:
def send_message(chat_id, text, reply_markup=None, retries=3, track_message=True):
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
                    message_id = result.get('result', {}).get('message_id')
                    # Track this message if requested
                    if message_id and track_message:
                        cleanup_chat_messages(chat_id, message_id)
                    return message_id
            
            if attempt < retries - 1:
                time.sleep(2)
                continue
                
        except Exception as e:
            print(f"Error sending message (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2)
            
    return None

# Update send_menu to use the new system:
def send_menu(chat_id):
    """Send simple menu with buttons, deleting previous menu first."""
    delete_previous_menu(chat_id)
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📊 Bot Status", "callback_data": "status"},
                {"text": "🔍 Check Now", "callback_data": "checknow"}
            ],
            [
                {"text": "✂️ Should I Get a Haircut?", "callback_data": "haircut"}
            ],
            [
                {"text": "🔕 Stop Notifications", "callback_data": "stop_notifications"}
            ]
        ]
    }
    
    message = "What would you like to do?"
    message_id = send_message(chat_id, message, reply_markup=keyboard, track_message=True)
    
    if message_id:
        last_menu_message_id[chat_id] = message_id

# Add this helper function to delete user messages:
def delete_user_message(chat_id, message_id):
    """Delete a user's message."""
    try:
        delete_message(chat_id, message_id)
    except Exception as e:
        print(f"Error deleting user message: {e}")
