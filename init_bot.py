import requests
import time
import re
from config import TOKEN, BASE_URL

def update_config(business_connection_id, admin_id, sender_username):
    """Update ALLOWED_BUSINESS_ID, ADMIN_ID, and SENDER_USERNAME in config.py."""
    config_file = 'config.py'
    try:
        with open(config_file, 'r') as f:
            content = f.read()
        
        # Replace ALLOWED_BUSINESS_ID
        content = re.sub(
            r"ALLOWED_BUSINESS_ID = '.*?'",
            f"ALLOWED_BUSINESS_ID = '{business_connection_id}'",
            content
        )
        
        # Replace ADMIN_ID
        content = re.sub(
            r"ADMIN_ID = \d+",
            f"ADMIN_ID = {admin_id}",
            content
        )
        
        # Replace SENDER_USERNAME
        content = re.sub(
            r"SENDER_USERNAME = '.*?'",
            f"SENDER_USERNAME = '{sender_username}'",
            content
        )
        
        with open(config_file, 'w') as f:
            f.write(content)
        
        print(f"[*] Updated config.py with:")
        print(f"    ALLOWED_BUSINESS_ID = '{business_connection_id}'")
        print(f"    ADMIN_ID = {admin_id}")
        print(f"    SENDER_USERNAME = '{sender_username}'")
    except Exception as e:
        print(f"[!] Error updating config.py: {e}")
        exit(1)

def print_connection_instructions():
    """Print instructions for setting up a business connection in Telegram."""
    print("\n[*] To set up the business connection, follow these steps:")
    print("1. Open Telegram and go to Settings > Business.")
    print("2. Under 'Telegram Bots', select 'Add Bot'.")
    print(f"3. Search for your bot and select it.")
    print("4. Confirm the connection in Telegram.")
    print("5. Return here and wait for the bot to detect the connection (may take up to 30 seconds).")
    print("\n[*] Waiting for business connection...")

def main():
    print("[*] Starting initialization bot to detect business connection...")
    print_connection_instructions()
    
    last_update_id = None
    
    while True:
        try:
            updates = requests.get(f'{BASE_URL}/getUpdates', params={
                'offset': last_update_id,
                'timeout': 30
            }, timeout=(10, 30)).json().get('result', [])
            
            for update in updates:
                last_update_id = update['update_id'] + 1
                
                if 'business_connection' in update:
                    business_connection = update['business_connection']
                    if business_connection.get('disabled', False):
                        print("[!] Business connection is disabled, please enable it in Telegram")
                        continue
                    
                    business_connection_id = business_connection['id']
                    admin_id = business_connection['user']['id']
                    sender_username = business_connection['user']['username'].lstrip('@')  # Remove @ prefix
                    
                    print(f"[*] Detected business connection:")
                    print(f"    Business Connection ID: {business_connection_id}")
                    print(f"    Admin ID: {admin_id}")
                    print(f"    Sender Username: @{sender_username}")
                    
                    # Update config.py
                    update_config(business_connection_id, admin_id, sender_username)
                    
                    print("[*] Initialization complete! You can now stop this script (Ctrl+C).")
                    print("[*] Run the main bot with: cd /opt/telegram-bot && python3 as.py")
                    print("[*] Or, if systemd service is set up, use: sudo systemctl start telegram-bot")
                    return
                
        except requests.exceptions.RequestException as e:
            print(f"[!] Network error: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"[!] Unexpected error: {e}")
            time.sleep(5)
        finally:
            time.sleep(1)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Initialization stopped by user")
        exit(0)