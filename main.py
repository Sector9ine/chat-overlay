from flask import Flask, request, render_template, jsonify
from flask_socketio import SocketIO, emit
import threading
import cloudscraper
import websocket
import json
import os

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
            socketio.emit('chat_message', data)
        except Exception as e:
            print("Error:", e)

    def on_open(ws):
        ws.send(json.dumps({
            "event": "pusher:subscribe",
            "data": {
                "auth": "",
                "channel": f"chatrooms.{chatroom_id}.v2"
            }
        }))

    ws = websocket.WebSocketApp(
        "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=8.4.0-rc2&flash=false",
        on_open=on_open,
        on_message=on_message
    )
    ws.run_forever()

@app.route('/')
def render_chat():
    return render_template('overlay.html')

thread = None

@socketio.on('connect')
def start_background_thread():
    global thread
    print('Client connected')
    if thread is None:
        thread = threading.Thread(target=listen_to_kick_chat, args=(chatroom_id,), daemon=True)
        thread.start()

socketio.run(app)


