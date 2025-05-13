# -*- coding: utf-8 -*-
# @Time    : 2023/3/22 14:17
# @Author  : Eg_Rek
# @File    : config.py
# @Software: Visual Studio Code
# @Telegram: https://t.me/eg_rek
# @Github  : https://github.com/Eg-rek

import sqlite3
import requests
import time
import os
import json
from datetime import datetime, timedelta
import schedule
import uuid
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config import *

# Global spam tracker
spam_tracker = {}

# Load spam tracker from JSON
def load_spam_tracker():
    global spam_tracker
    try:
        if os.path.exists('spam_tracker.json'):
            with open('spam_tracker.json', 'r') as f:
                spam_tracker = json.load(f)
                # Convert user_id keys to integers
                spam_tracker = {int(k): v for k, v in spam_tracker.items()}
        else:
            spam_tracker = {}
    except Exception as e:
        print(f"Error loading spam_tracker: {e}")
        spam_tracker = {}

# Save spam tracker to JSON
def save_spam_tracker():
    try:
        with open('spam_tracker.json', 'w') as f:
            json.dump(spam_tracker, f, indent=2)
    except Exception as e:
        print(f"Error saving spam_tracker: {e}")

# Initialize DB and folders
def init_db():
    os.makedirs(MEDIA_DIR, exist_ok=True)
    
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY,
                  message_id INT,
                  chat_id INT,
                  user_id INT,
                  username TEXT,
                  text TEXT,
                  original_text TEXT,
                  date INT,
                  business_id TEXT,
                  media_type TEXT,
                  media_path TEXT,
                  original_media_type TEXT,
                  original_media_path TEXT,
                  is_deleted BOOLEAN DEFAULT 0,
                  is_edited BOOLEAN DEFAULT 0,
                  forward_from TEXT,
                  forward_from_chat INT,
                  forward_from_message_id INT)''')
    conn.commit()
    conn.close()

# Download and save media file
def download_media(file_id, file_type):
    try:
        file_info = requests.get(f'{BASE_URL}/getFile?file_id={file_id}').json()
        file_path = file_info['result']['file_path']
        file_size = file_info['result'].get('file_size', 0)
        
        if file_size > MAX_FILE_SIZE:
            print(f"File {file_path} exceeds 50 MB, ignoring.")
            return None
        
        file_url = f'https://api.telegram.org/file/bot{TOKEN}/{file_path}'
        local_path = f"{MEDIA_DIR}/{file_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4()}.{os.path.splitext(file_path)[1]}"
        
        with requests.get(file_url, stream=True) as r:
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        return local_path
    except Exception as e:
        print(f"Media download error: {e}")
        return None

# Check for spam (too many photos) and block media if needed
def check_spam(user_id, username, first_name, last_name, media_type, msg_data):
    current_time = time.time()
    user_info = f"{first_name} {last_name}".strip() if last_name else first_name
    
    # Initialize user in spam_tracker if not present
    if user_id not in spam_tracker:
        spam_tracker[user_id] = {'photos': [], 'block_until': 0, 'notified': False}
    
    # Check if user is blocked
    if current_time < spam_tracker[user_id]['block_until']:
        if media_type in ['photo', 'video', 'document', 'voice', 'audio']:
            print(f"🚫 Ignored media ({media_type}) from @{username} ({user_info}) due to spam block")
            return True  # Skip media
        return False  # Allow non-media messages
    
    # Only track photos for spam detection
    if media_type == 'photo':
        # Clean up old photo entries
        spam_tracker[user_id]['photos'] = [
            (t, c) for t, c in spam_tracker[user_id]['photos'] if current_time - t < SPAM_WINDOW
        ]
        
        # Add new photo
        spam_tracker[user_id]['photos'].append((current_time, 1))
        
        # Count total photos in the window
        photo_count = sum(count for _, count in spam_tracker[user_id]['photos'])
        
        if photo_count > SPAM_THRESHOLD:
            # Set block duration
            spam_tracker[user_id]['block_until'] = current_time + SPAM_BLOCK_DURATION
            
            # Send alert only if not notified yet
            if not spam_tracker[user_id]['notified']:
                print(f"⚠️ Spam detected from @{username} ({user_info}): {photo_count} photos, blocking media for 1 hour")
                alert_item = {
                    'username': username,
                    'date': msg_data['date'],
                    'photo_count': photo_count
                }
                send_alert([alert_item], msg_data['business_connection_id'], msg_data['chat'], event_type='spam')
                spam_tracker[user_id]['notified'] = True
            
            save_spam_tracker()  # Save updated tracker
            return True  # Skip media
    
    save_spam_tracker()  # Save updated tracker
    return False

# Mark message as edited and update text and media
def mark_edited(business_id, chat_id, message_id, new_msg_data):
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    
    c.execute('''SELECT text, media_type, media_path FROM messages 
                 WHERE message_id = ? AND chat_id = ? AND business_id = ?''',
              (message_id, chat_id, business_id))
    result = c.fetchone()
    
    new_text = new_msg_data.get('text', '')
    new_media_type = None
    new_media_path = None
    
    if 'photo' in new_msg_data:
        new_media_type = 'photo'
        file_id = new_msg_data['photo'][-1]['file_id']
        new_media_path = download_media(file_id, 'photo')
    elif 'video' in new_msg_data:
        new_media_type = 'video'
        new_media_path = download_media(new_msg_data['video']['file_id'], 'video')
    elif 'document' in new_msg_data:
        new_media_type = 'document'
        new_media_path = download_media(new_msg_data['document']['file_id'], 'document')
    elif 'voice' in new_msg_data:
        new_media_type = 'voice'
        new_media_path = download_media(new_msg_data['voice']['file_id'], 'voice')
    elif 'audio' in new_msg_data:
        new_media_type = 'audio'
        new_media_path = download_media(new_msg_data['audio']['file_id'], 'audio')
    
    if result:
        current_text, current_media_type, current_media_path = result
        c.execute('''UPDATE messages 
                     SET is_edited = 1, 
                         text = ?, 
                         original_text = COALESCE(original_text, ?),
                         media_type = ?,
                         media_path = ?,
                         original_media_type = COALESCE(original_media_type, ?),
                         original_media_path = COALESCE(original_media_path, ?)
                     WHERE message_id = ? AND chat_id = ? AND business_id = ?''',
                  (new_text, current_text, new_media_type, new_media_path, 
                   current_media_type, current_media_path, message_id, chat_id, business_id))
    else:
        c.execute('''UPDATE messages 
                     SET is_edited = 1, text = ?, media_type = ?, media_path = ?
                     WHERE message_id = ? AND chat_id = ? AND business_id = ?''',
                  (new_text, new_media_type, new_media_path, message_id, chat_id, business_id))
    
    conn.commit()
    conn.close()

# Clean up old messages and media
def cleanup_old_data():
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    
    cutoff_time = int((datetime.now() - timedelta(days=CLEANUP_DAYS)).timestamp())
    
    c.execute('''SELECT media_path, original_media_path FROM messages 
                 WHERE date < ? AND (media_path IS NOT NULL OR original_media_path IS NOT NULL)''',
              (cutoff_time,))
    media_files = c.fetchall()
    
    deleted_files = set()
    for media_path, original_media_path in media_files:
        for path in [media_path, original_media_path]:
            if path and path not in deleted_files and os.path.exists(path):
                try:
                    os.remove(path)
                    deleted_files.add(path)
                    print(f"Deleted media file: {path}")
                except Exception as e:
                    print(f"Error deleting media {path}: {e}")
    
    c.execute('''DELETE FROM messages WHERE date < ?''', (cutoff_time,))
    deleted_rows = c.rowcount
    conn.commit()
    conn.close()
    
    print(f"Cleared {deleted_rows} old messages and {len(deleted_files)} media files.")

# Save message to DB
def save_message(msg_data, business_id=None):
    if business_id != ALLOWED_BUSINESS_ID:
        return
    
    username = msg_data['from'].get('username')
    if username and username.lower() == SENDER_USERNAME:
        return
    
    user_id = msg_data['from']['id']
    first_name = msg_data['from'].get('first_name', '')
    last_name = msg_data['from'].get('last_name', '')
    user_info = f"{first_name} {last_name}".strip() if last_name else first_name
    
    media_type = None
    media_path = None
    text = msg_data.get('text', '')
    
    # Check for spam or block before processing media
    if 'photo' in msg_data:
        media_type = 'photo'
        if check_spam(user_id, username, first_name, last_name, media_type, msg_data):
            return
        file_id = msg_data['photo'][-1]['file_id']
        media_path = download_media(file_id, 'photo')
    elif 'video' in msg_data:
        media_type = 'video'
        if check_spam(user_id, username, first_name, last_name, media_type, msg_data):
            return
        media_path = download_media(msg_data['video']['file_id'], 'video')
    elif 'document' in msg_data:
        media_type = 'document'
        if check_spam(user_id, username, first_name, last_name, media_type, msg_data):
            return
        media_path = download_media(msg_data['document']['file_id'], 'document')
    elif 'voice' in msg_data:
        media_type = 'voice'
        if check_spam(user_id, username, first_name, last_name, media_type, msg_data):
            return
        media_path = download_media(msg_data['voice']['file_id'], 'voice')
    elif 'audio' in msg_data:
        media_type = 'audio'
        if check_spam(user_id, username, first_name, last_name, media_type, msg_data):
            return
        media_path = download_media(msg_data['audio']['file_id'], 'audio')
    
    print(f"📩 Saved message + media from @{username} ({user_info})")
    
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    
    forward_from = None
    forward_from_chat = None
    forward_from_message_id = None
    if 'forward_from' in msg_data:
        forward_from = msg_data['forward_from'].get('username') or msg_data['forward_from'].get('first_name')
    elif 'forward_from_chat' in msg_data:
        forward_from_chat = msg_data['forward_from_chat'].get('id')
        forward_from_message_id = msg_data.get('forward_from_message_id')
    
    c.execute('''INSERT INTO messages 
                 (message_id, chat_id, user_id, username, text, original_text, date, business_id, 
                  media_type, media_path, original_media_type, original_media_path,
                  forward_from, forward_from_chat, forward_from_message_id)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (msg_data['message_id'],
               msg_data['chat']['id'],
               user_id,
               username,
               text,
               text,
               msg_data['date'],
               business_id,
               media_type,
               media_path,
               media_type,
               media_path,
               forward_from,
               forward_from_chat,
               forward_from_message_id))
    conn.commit()
    conn.close()

# Handle edited messages
def handle_edited(business_id, chat_id, message_id, new_msg_data):
    if business_id != ALLOWED_BUSINESS_ID:
        return None
    
    mark_edited(business_id, chat_id, message_id, new_msg_data)
    
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    
    c.execute('''SELECT original_text, text, username, media_type, media_path, 
                        original_media_type, original_media_path, date 
                 FROM messages 
                 WHERE message_id = ? AND chat_id = ? AND business_id = ?''',
              (message_id, chat_id, business_id))
    result = c.fetchone()
    
    edited_info = None
    if result:
        original_text, current_text, username, media_type, media_path, \
        original_media_type, original_media_path, date = result
        edited_info = {
            'original_text': original_text or '',
            'text': current_text or '',
            'username': username,
            'media_type': media_type,
            'media_path': media_path,
            'original_media_type': original_media_type,
            'original_media_path': original_media_path,
            'date': date
        }
    
    conn.close()
    return edited_info

# Handle deleted messages
def handle_deleted(business_id, chat_id, message_ids):
    if business_id != ALLOWED_BUSINESS_ID:
        return []
    
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    
    deleted_info = []
    
    for msg_id in message_ids:
        c.execute('''SELECT text, username, media_type, media_path, date FROM messages 
                     WHERE message_id = ? AND chat_id = ? AND business_id = ?''',
                  (msg_id, chat_id, business_id))
        result = c.fetchone()
        
        if result:
            text, username, media_type, media_path, date = result
            mark_deleted(business_id, chat_id, [msg_id])
            
            deleted_info.append({
                'text': text,
                'username': username,
                'media_type': media_type,
                'media_path': media_path,
                'date': date
            })
    
    conn.close()
    return deleted_info

# Mark message as deleted in DB
def mark_deleted(business_id, chat_id, message_ids):
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    
    for msg_id in message_ids:
        c.execute('''UPDATE messages 
                     SET is_deleted = 1 
                     WHERE message_id = ? 
                     AND chat_id = ? 
                     AND business_id = ?''',
                  (msg_id, chat_id, business_id))
    
    conn.commit()
    conn.close()

# Send alert to admin
def send_alert(items, business_id, chat_info, event_type='deleted'):
    for item in items:
        if event_type == 'edited':
            alert = f"✏️ Message edited in business chat!\n\n"
            alert += f"From: @{item['username']}\n"
            alert += f"Date: {datetime.fromtimestamp(item['date'])}\n"
            if item['original_text']:
                alert += f"Old text: {item['original_text'][:300]}\n"
            if item['text']:
                alert += f"New text: {item['text'][:300]}\n"
            if item['original_media_type']:
                alert += f"Old media: {item['original_media_type']}\n"
            if item['media_type']:
                alert += f"New media: {item['media_type']}\n"
        elif event_type == 'spam':
            alert = f"🚨 Spam detected in business chat!\n\n"
            alert += f"From: @{item['username']}\n"
            alert += f"Date: {datetime.fromtimestamp(item['date'])}\n"
            alert += f"Sent {item['photo_count']} photos in the last minute\n"
            alert += f"Media from this user will be ignored for 1 hour"
        else:
            alert = f"🚨 Message deleted in business chat!\n\n"
            alert += f"From: @{item['username']}\n"
            alert += f"Date: {datetime.fromtimestamp(item['date'])}\n"
            if item['text']:
                alert += f"Text: {item['text'][:300]}\n"
            if item['media_type']:
                alert += f"Media: {item['media_type']}\n"
        
        if event_type == 'edited' and item['original_media_path'] and os.path.exists(item['original_media_path']):
            with open(item['original_media_path'], 'rb') as f:
                files = {'document': f}
                data = {
                    'chat_id': ADMIN_ID,
                    'caption': f"{alert}Old media:"[:1024]
                }
                requests.post(f'{BASE_URL}/sendDocument', data=data, files=files)
        
        if event_type != 'spam' and item['media_path'] and os.path.exists(item['media_path']):
            with open(item['media_path'], 'rb') as f:
                files = {'document': f}
                data = {
                    'chat_id': ADMIN_ID,
                    'caption': f"{alert}New media:"[:1024] if event_type == 'edited' else alert[:1024]
                }
                requests.post(f'{BASE_URL}/sendDocument', data=data, files=files)
            return
        
        requests.post(f'{BASE_URL}/sendMessage', json={
            'chat_id': ADMIN_ID,
            'text': alert
        })
def get_project_size():
    """Calculate and return the total size of the project directory in human-readable format"""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk('.'):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # Skip if it's symbolic link or doesn't exist
            if not os.path.islink(fp) and os.path.exists(fp):
                total_size += os.path.getsize(fp)
    
    # Convert size to human-readable format
    def sizeof_fmt(num, suffix='B'):
        for unit in ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
            if abs(num) < 1024.0:
                return f"{num:.1f}{unit}{suffix}"
            num /= 1024.0
        return f"{num:.1f}Y{suffix}"
    
    return sizeof_fmt(total_size)

# Handle commands
def handle_command(update):
    if 'message' in update and 'text' in update['message']:
        msg = update['message']
        if msg['from']['id'] != ADMIN_ID:
            return
        
        command = msg['text'].split()[0]  # Get the first word (command)
        
        if command == '/stats':
            conn = sqlite3.connect('messages.db')
            c = conn.cursor()
            
            c.execute('SELECT COUNT(*) FROM messages')
            total_msgs = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM messages WHERE is_deleted = 1')
            deleted_msgs = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM messages WHERE is_edited = 1')
            edited_msgs = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM messages WHERE media_type IS NOT NULL')
            media_msgs = c.fetchone()[0]
            
            stats = (
                f"📊 Statistics:\n"
                f"Total messages: {total_msgs}\n"
                f"Deleted: {deleted_msgs}\n"
                f"Edited: {edited_msgs}\n"
                f"With media: {media_msgs}"
            )
            
            requests.post(f'{BASE_URL}/sendMessage', json={
                'chat_id': ADMIN_ID,
                'text': stats
            })
            
            conn.close()
        
        elif command == '/size':
            size = get_project_size()
            requests.post(f'{BASE_URL}/sendMessage', json={
                'chat_id': ADMIN_ID,
                'text': f"📁 Project directory size: {size}"
            })

# Backup database
def backup_db():
    backup_path = f"messages_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    try:
        # Create backup
        with open('messages.db', 'rb') as src, open(backup_path, 'wb') as dst:
            dst.write(src.read())
        
        # Get directory size
        dir_size = get_project_size()
        caption = f"Daily database backup\n\nProject directory size: {dir_size}"
        
        # Send backup
        with open(backup_path, 'rb') as f:
            files = {'document': (backup_path, f)}
            data = {'chat_id': ADMIN_ID, 'caption': caption}
            requests.post(f'{BASE_URL}/sendDocument', data=data, files=files)
        
        os.remove(backup_path)
        print(f"Backup sent: {backup_path} | Directory size: {dir_size}")
    except Exception as e:
        print(f"Backup error: {e}")

# Create a session with retry logic
def create_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

# Main processing loop
def process_update(update):
    handle_command(update)
    if 'business_message' in update:
        msg = update['business_message']
        business_id = msg['business_connection_id']
        if business_id != ALLOWED_BUSINESS_ID:
            return
            
        save_message(msg, business_id)
    
    elif 'edited_business_message' in update:
        edited = update['edited_business_message']
        business_id = edited['business_connection_id']
        if business_id != ALLOWED_BUSINESS_ID:
            return
            
        edited_item = handle_edited(
            business_id,
            edited['chat']['id'],
            edited['message_id'],
            edited
        )
        
        if edited_item:
            username = edited_item['username'] or ''
            first_name = edited.get('from', {}).get('first_name', '')
            last_name = edited.get('from', {}).get('last_name', '')
            user_info = f"{first_name} {last_name}".strip() if last_name else first_name
            send_alert([edited_item], business_id, edited['chat'], event_type='edited')
            print(f"✏️ Recorded message edit from @{username} ({user_info})")
    
    elif 'deleted_business_messages' in update:
        deleted = update['deleted_business_messages']
        business_id = deleted['business_connection_id']
        if business_id != ALLOWED_BUSINESS_ID:
            return
            
        deleted_items = handle_deleted(
            business_id,
            deleted['chat']['id'],
            deleted['message_ids']
        )
        
        if deleted_items:
            for item in deleted_items:
                username = item['username'] or ''
                first_name = deleted.get('from', {}).get('first_name', '')
                last_name = deleted.get('from', {}).get('last_name', '')
                user_info = f"{first_name} {last_name}".strip() if last_name else first_name
                print(f"⚠️ Recorded deletion of {len(deleted_items)} messages from @{username} ({user_info})")
            send_alert(deleted_items, business_id, deleted['chat'])

def main():
    init_db()
    load_spam_tracker()  # Load spam tracker at startup
    print("🛡️ Archive bot started. Tracking messages, media, edits, and deletions...")
    
    schedule.every().day.at("00:00").do(backup_db)
    schedule.every().day.at("00:03").do(cleanup_old_data)
    
    last_update_id = None
    session = create_session()  # Create a session with retry logic
    
    while True:
        try:
            updates = session.get(f'{BASE_URL}/getUpdates', params={
                'offset': last_update_id,
                'timeout': 30
            }, timeout=(10, 30)).json().get('result', [])
            
            for update in updates:
                last_update_id = update['update_id'] + 1
                process_update(update)
                
            schedule.run_pending()
            
        except requests.exceptions.ConnectionError as e:
            print(f"Connection error while fetching updates: {e}")
            time.sleep(5)  # Wait before retrying
        except requests.exceptions.Timeout as e:
            print(f"Timeout error while fetching updates: {e}")
            time.sleep(5)  # Wait before retrying
        except requests.exceptions.RequestException as e:
            print(f"Request error while fetching updates: {e}")
            time.sleep(5)  # Wait before retrying
        except Exception as e:
            print(f"Unexpected error: {e}")
            time.sleep(5)  # Wait before retrying
        finally:
            time.sleep(1)

if __name__ == '__main__':
    main()