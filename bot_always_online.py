def handle_telegram_updates():
    """Main bot loop - handles messages and button presses."""
    print("Starting Telegram bot...")
    
    load_users()
    
    if active_chat_ids:
        print("Notifying users about restart...")
        notify_restart()
    
    offset = None
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    check_thread = Thread(target=automated_check_loop, daemon=True)
    check_thread.start()

    server_thread = Thread(target=run_http_server, daemon=True)
    server_thread.start()
    
    # Create a session for Telegram API calls with keep-alive
    telegram_session = requests.Session()
    telegram_session.headers.update({
        "Connection": "keep-alive"
    })
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {
                "timeout": 30,
                "allowed_updates": ["message", "callback_query"]  # Only get what we need
            }
            if offset:
                params["offset"] = offset
            
            # Use session with longer timeout and keep-alive
            response = telegram_session.get(url, params=params, timeout=40)
            
            # Check if response is valid
            if response.status_code != 200:
                print(f"HTTP error: {response.status_code}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print("Too many errors, recreating session...")
                    telegram_session = requests.Session()
                    telegram_session.headers.update({"Connection": "keep-alive"})
                    consecutive_errors = 0
                time.sleep(5)
                continue
            
            data = response.json()
            
            if not data.get('ok'):
                print(f"Telegram API error: {data.get('description', 'Unknown error')}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print("Too many errors, recreating session...")
                    telegram_session = requests.Session()
                    telegram_session.headers.update({"Connection": "keep-alive"})
                    consecutive_errors = 0
                time.sleep(5)
                continue
            
            # Reset error counter on successful request
            consecutive_errors = 0
            
            updates = data.get('result', [])
            
            # If we got updates, process them (same as your existing code)
            for update in updates:
                offset = update['update_id'] + 1
                
                # Handle button presses
                if 'callback_query' in update:
                    callback = update['callback_query']
                    callback_data = callback.get('data', '')
                    chat_id = callback['message']['chat']['id']
                    callback_query_id = callback['id']
                    message_id = callback['message']['message_id']
                    
                    # Check if user is authenticated
                    if chat_id not in authenticated_users:
                        answer_callback(callback_query_id, "Please authenticate first!")
                        send_password_prompt(chat_id)
                        continue
                    
                    # Rate limiting check
                    if not check_rate_limit(chat_id):
                        answer_callback(callback_query_id, "Rate limited! Please wait.")
                        remaining_wait = RATE_LIMIT_WINDOW - (time.time() - min(user_request_times[chat_id]))
                        send_message(chat_id, f"⚠️ <b>Rate Limited</b>\n\nPlease wait {int(remaining_wait)} seconds before making more requests.\n\nLimit: {RATE_LIMIT_REQUESTS} requests per minute.")
                        continue
                    
                    active_chat_ids.add(chat_id)
                    
                    if callback_data == 'status':
                        answer_callback(callback_query_id)
                        
                        status_msg = f"""📊 <b>Bot Status</b>

🤖 Status: <b>Running</b>
🕐 Last check: <b>{last_check_string}</b>
📅 Last slot found: <b>{get_time_since_last_slot()}</b>
🔍 Monitoring: Next 30 days

👥 Active users: {len(active_chat_ids)}
🔢 Your requests: {get_rate_limit_remaining(chat_id)}/{RATE_LIMIT_REQUESTS} remaining"""
                        send_message(chat_id, status_msg)
                        send_menu(chat_id)
                        
                    elif callback_data == 'checknow':
                        answer_callback(callback_query_id)
                        
                        checking_msg_id = send_message(chat_id, "🔍 Checking next 3 months...\n\nThis may take a moment.")
                        
                        found_any_slots, results = do_slot_check(full_check=True)
                        
                        if checking_msg_id:
                            delete_message(chat_id, checking_msg_id)
                        
                        if found_any_slots:
                            message = format_results_simple(results)
                            send_message(chat_id, message)
                        else:
                            send_message(chat_id, "❌ <b>No slots found</b>\n\nNo appointments available in the next 3 months.\n\nI'll notify you automatically when something opens up!")
                        
                        send_menu(chat_id)
                        
                    elif callback_data == 'haircut':
                        answer_callback(callback_query_id)
                        
                        advice = random.choice(HAIRCUT_ADVICE)
                        send_message(chat_id, f"✂️ <i>{advice}</i>")
                        send_menu(chat_id)
                    
                    elif callback_data == 'stop_notifications':
                        answer_callback(callback_query_id, "Notifications stopped")
                        active_chat_ids.discard(chat_id)
                        delete_previous_menu(chat_id)
                        save_users()
                        send_message(chat_id, "🔕 <b>Unsubscribed</b>\n\nYou will no longer receive automatic notifications.\n\nSend any message to re-subscribe.")
                
                # Handle text messages
                elif 'message' in update:
                    message = update['message']
                    chat_id = message['chat']['id']
                    text = message.get('text', '').strip()
                    
                    if chat_id not in authenticated_users:
                        if text.lower() == '/start':
                            send_password_prompt(chat_id)
                            continue
                        
                        if text == BOT_PASSWORD:
                            authenticated_users.add(chat_id)
                            active_chat_ids.add(chat_id)
                            save_users()
                            send_welcome_message(chat_id)
                            send_menu(chat_id)
                        else:
                            send_message(chat_id, "❌ <b>Incorrect password</b>\n\nPlease try again:")
                        continue
                    
                    if text.lower() == '/start':
                        active_chat_ids.add(chat_id)
                        save_users()
                        delete_previous_menu(chat_id)
                        send_menu(chat_id)
                        continue
                    
                    if not check_rate_limit(chat_id):
                        send_message(chat_id, f"⚠️ <b>Rate Limited</b>\n\nPlease wait before making more requests.\n\nLimit: {RATE_LIMIT_REQUESTS} requests per minute.")
                        continue
                    
                    if chat_id not in active_chat_ids:
                        active_chat_ids.add(chat_id)
                        save_users()
                        send_message(chat_id, "🔔 <b>Re-subscribed!</b>\n\nYou'll now receive notifications again.")
                    
                    send_menu(chat_id)
            
            # Print heartbeat every 30 requests to show bot is alive
            if offset and offset % 30 == 0:
                print(f"Bot alive - processed {offset} updates")
        
        except requests.exceptions.Timeout:
            print("Request timeout - retrying...")
            consecutive_errors += 1
            time.sleep(2)
            
        except requests.exceptions.ConnectionError as e:
            print(f"Connection error: {e} - retrying...")
            consecutive_errors += 1
            # Recreate session on connection errors
            telegram_session = requests.Session()
            telegram_session.headers.update({"Connection": "keep-alive"})
            time.sleep(5)
            
        except Exception as e:
            print(f"Unexpected error: {e}")
            consecutive_errors += 1
            time.sleep(5)
        
        # If too many consecutive errors, wait longer and recreate session
        if consecutive_errors >= max_consecutive_errors:
            print(f"Too many consecutive errors ({consecutive_errors}), waiting 30 seconds...")
            telegram_session = requests.Session()
            telegram_session.headers.update({"Connection": "keep-alive"})
            time.sleep(30)
            consecutive_errors = 0
