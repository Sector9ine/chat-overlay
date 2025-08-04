import eventlet
eventlet.monkey_patch()
from flask import Flask, request, render_template, jsonify
from flask_socketio import SocketIO, emit
import threading
import cloudscraper
import websocket
import json
import os
import redis
import time
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret'
socketio = SocketIO(app, async_mode='threading')

kick_slug = 'zam-live'

def get_chatroom_id(slug):
    endpoint = f"https://kick.com/api/v2/channels/{slug}"
    scraper = cloudscraper.create_scraper()
    r = scraper.get(endpoint)
    data = r.json()
    chatroom_id = data.get("chatroom_id")
    if not chatroom_id and "chatroom" in data:
        chatroom_id = data["chatroom"].get("id")
    return chatroom_id

chatroom_id = get_chatroom_id(kick_slug)

def detect_and_handle_events(data):
    """Detect subscription and gift subscription events and trigger actions"""
    try:
        # Parse the data field
        if isinstance(data.get('data'), str):
            event_data = json.loads(data['data'])
        else:
            event_data = data.get('data', {})
        
        content = event_data.get('content', '')
        sender_username = event_data.get('sender', {}).get('username', '')
        
        # Check if it's a KickBot message (system messages)
        if sender_username == 'KickBot':
            # Detect gift subscription
            gift_match = re.search(r'@(\w+)\s+just gifted\s+(\d+)\s+subs?', content)
            if gift_match:
                gifter = gift_match.group(1)
                gift_count = int(gift_match.group(2))
                print(f"🎁 GIFT SUB DETECTED: {gifter} gifted {gift_count} subs!")
                trigger_gift_sub_action(gifter, gift_count)
                return
            
            # Detect regular subscription
            sub_match = re.search(r'@(\w+)\s+has subbed for\s+(\d+)\s+months?', content)
            if sub_match:
                subscriber = sub_match.group(1)
                months = int(sub_match.group(2))
                print(f"⭐ SUB DETECTED: {subscriber} subscribed for {months} months!")
                trigger_sub_action(subscriber, months)
                return
            
            # Detect first-time subscription (no months mentioned)
            first_sub_match = re.search(r'@(\w+)\s+has subbed!', content)
            if first_sub_match:
                subscriber = first_sub_match.group(1)
                print(f"⭐ FIRST SUB DETECTED: {subscriber} subscribed!")
                trigger_sub_action(subscriber, 1)
                return
                
    except Exception as e:
        print(f"Error in event detection: {e}")

def trigger_gift_sub_action(gifter, gift_count):
    """Trigger action for gift subscription event"""
    print(f"🎁 ACTION TRIGGERED: {gifter} gifted {gift_count} subs!")
    
    # Add your custom actions here:
    # Examples:
    # - Play a sound
    # - Show an animation
    # - Send a webhook
    # - Update a counter
    # - Trigger OBS scene change
    
    # Emit to frontend for visual effects
    socketio.emit('gift_sub_event', {
        'gifter': gifter,
        'count': gift_count,
        'timestamp': time.time()
    })
    
    # Save to Redis for tracking
    save_event_to_redis('gift_sub', {
        'gifter': gifter,
        'count': gift_count,
        'timestamp': time.time()
    })

def trigger_sub_action(subscriber, months):
    """Trigger action for subscription event"""
    print(f"⭐ ACTION TRIGGERED: {subscriber} subscribed for {months} months!")
    
    # Add your custom actions here:
    # Examples:
    # - Play a sound
    # - Show an animation
    # - Send a webhook
    # - Update a counter
    # - Trigger OBS scene change
    
    # Emit to frontend for visual effects
    socketio.emit('sub_event', {
        'subscriber': subscriber,
        'months': months,
        'timestamp': time.time()
    })
    
    # Save to Redis for tracking
    save_event_to_redis('sub', {
        'subscriber': subscriber,
        'months': months,
        'timestamp': time.time()
    })

def save_event_to_redis(event_type, event_data):
    """Save event to Redis for tracking"""
    try:
        event_key = f"{event_type}_events"
        r.rpush(event_key, json.dumps(event_data))
        r.ltrim(event_key, -100, -1)  # Keep last 100 events
    except Exception as e:
        print(f"Error saving event to Redis: {e}")

def listen_to_kick_chat(chatroom_id):
    def on_message(ws, message):
        try:
            data = json.loads(message)
            print("Received message:", data)
            
            # Handle Pusher ping messages
            if data.get("event") == "pusher:ping":
                print("Received ping, sending pong...")
                ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                return
            
            # Check if it's a Pusher error that requires reconnection
            if data.get("event") == "pusher:error":
                error_data = data.get("data", {})
                error_code = error_data.get("code")
                print(f"Pusher error {error_code}: {error_data.get('message')}")
                
                # Handle specific error codes
                if error_code in [4200, 4201, 4202]:  # Connection errors
                    print(f"Pusher error {error_code} - reconnecting...")
                    ws.close()
                    return
            
            # Detect and handle subscription events
            detect_and_handle_events(data)
            
            socketio.emit('chat_message', data)
            save_message(data)  # Save to Redis
        except Exception as e:
            print("Error:", e)

    def on_error(ws, error):
        print(f"WebSocket error: {error}")

    def on_close(ws, close_status_code, close_msg):
        print(f"WebSocket connection closed: {close_status_code} - {close_msg}")
        # Attempt to reconnect after a delay
        time.sleep(5)
        print("Attempting to reconnect...")
        start_websocket_connection()

    def on_open(ws):
        print("WebSocket connection opened")
        # Subscribe to the chatroom
        ws.send(json.dumps({
            "event": "pusher:subscribe",
            "data": {
                "auth": "",
                "channel": f"chatrooms.{chatroom_id}.v2"
            }
        }))

    def start_websocket_connection():
        try:
            # Enable ping/pong handling and set keepalive
            ws = websocket.WebSocketApp(
                "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=8.4.0-rc2&flash=false",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            # Set ping interval and timeout for better connection stability
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print(f"Failed to start WebSocket connection: {e}")
            # Retry after delay
            time.sleep(10)
            start_websocket_connection()

    # Start the initial connection
    start_websocket_connection()

@app.route('/')
def render_chat():
    return render_template('overlay.html')

@app.route('/animation')
def render_animation():
    return render_template('animation.html')

@app.route('/api/events/stats')
def get_event_stats():
    """Get statistics about subscription events"""
    try:
        # Get recent events from Redis
        sub_events = [json.loads(e) for e in r.lrange('sub_events', 0, -1)]
        gift_sub_events = [json.loads(e) for e in r.lrange('gift_sub_events', 0, -1)]
        
        # Calculate stats
        total_subs = len(sub_events)
        total_gift_subs = len(gift_sub_events)
        total_gifted_subs = sum(e.get('count', 1) for e in gift_sub_events)
        
        # Recent events (last 10)
        recent_subs = sub_events[-10:] if sub_events else []
        recent_gift_subs = gift_sub_events[-10:] if gift_sub_events else []
        
        return jsonify({
            'total_subs': total_subs,
            'total_gift_subs': total_gift_subs,
            'total_gifted_subs': total_gifted_subs,
            'recent_subs': recent_subs,
            'recent_gift_subs': recent_gift_subs
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/events/clear')
def clear_events():
    """Clear all event history"""
    try:
        r.delete('sub_events', 'gift_sub_events')
        return jsonify({'message': 'Events cleared successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

thread = None

# Connect to Redis (use Railway's Redis URL in production)
redis_url = os.environ.get("REDIS_URL")
r = redis.from_url(redis_url, decode_responses=True)

CHAT_HISTORY_KEY = "chat_history"
MAX_HISTORY = 100  # Number of messages to keep

def save_message(msg):
    r.rpush(CHAT_HISTORY_KEY, json.dumps(msg))
    r.ltrim(CHAT_HISTORY_KEY, -MAX_HISTORY, -1)

def get_history():
    return [json.loads(m) for m in r.lrange(CHAT_HISTORY_KEY, 0, -1)]

@socketio.on('connect')
def start_background_thread():
    global thread
    print('Client connected')
    if thread is None:
        thread = threading.Thread(target=listen_to_kick_chat, args=(chatroom_id,), daemon=True)
        thread.start()
    # Send chat history to the client
    for msg in get_history():
        emit('chat_message', msg)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)


