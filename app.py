from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(16)
socketio = SocketIO(app, cors_allowed_origins="*")

# хранение участников: room_id -> set(socket.id)
rooms = {}

@app.route('/')
def index():
    return render_template("index.html")

@socketio.on("join")
def handle_join(data):
    room = data["room"]
    join_room(room)
    if room not in rooms:
        rooms[room] = set()
    # уведомить других
    for sid in rooms[room]:
        emit("peer-joined", {"id": request.sid}, room=sid)
    # отправить список участников новому
    emit("peers", {"peers": list(rooms[room]), "you": request.sid})
    rooms[room].add(request.sid)

@socketio.on("signal")
def handle_signal(data):
    to = data.get("to")
    emit("signal", data, room=to)

@socketio.on("leave")
def handle_leave(data):
    room = data["room"]
    leave_room(room)
    if room in rooms and request.sid in rooms[room]:
        rooms[room].remove(request.sid)
        emit("peer-left", {"id": request.sid}, room=room)

@socketio.on("disconnect")
def handle_disconnect():
    # убрать из всех комнат
    for room, members in list(rooms.items()):
        if request.sid in members:
            members.remove(request.sid)
            emit("peer-left", {"id": request.sid}, room=room)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
