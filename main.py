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

def listen_to_kick_chat(chatroom_id):
    def on_message(ws, message):
        try:
            data = json.loads(message)
            print("Received message:", data)
            
            # Check if it's a Pusher error that requires reconnection
            if data.get("event") == "pusher:error":
                error_data = data.get("data", {})
                if error_data.get("code") == 4200:
                    print("Pusher error 4200 - reconnecting...")
                    ws.close()
                    return
            
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
        ws.send(json.dumps({
            "event": "pusher:subscribe",
            "data": {
                "auth": "",
                "channel": f"chatrooms.{chatroom_id}.v2"
            }
        }))

    def start_websocket_connection():
        try:
            ws = websocket.WebSocketApp(
                "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=8.4.0-rc2&flash=false",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever()
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

@app.route('/z')
def z_ascii():
    return render_template('z_ascii.html')

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


