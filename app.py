"""
Simple working WebRTC conferencing demo using Flask + Flask-SocketIO (no React/Node).
Single-file app: run this Python file and open several browser tabs to test.

Features:
- Flask serves a minimal HTML/JS client (vanilla JS)
- Flask-SocketIO used for signaling (offer/answer/ICE exchange)
- Mesh topology: every participant creates a peer connection with every other participant

Limitations:
- Mesh scales poorly (OK for 2-6 participants)
- No TURN server configured (use coturn for NAT traversal in production)

Requirements:
pip install flask flask-socketio eventlet

Run:
python webrtc_flask_app.py
Open http://localhost:5000 and join a room (open multiple tabs or different browsers)

"""
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import eventlet
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='eventlet')

# In-memory room -> { sid: {"name": name} }
ROOMS = {}

INDEX_HTML = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Flask WebRTC Demo</title>
    <style>
      body { font-family: sans-serif; margin: 12px; }
      #videos { display:flex; flex-wrap:wrap; gap:8px }
      video { width: 320px; height: 240px; background: #000 }
      #controls { margin-bottom:12px }
    </style>
  </head>
  <body>
    <h2>Flask + WebRTC (vanilla JS) — Simple Conference</h2>
    <div id="controls">
      Name: <input id="name" value="User" />
      Room: <input id="room" value="test" />
      <button id="joinBtn">Join Room</button>
      <button id="leaveBtn" disabled>Leave</button>
    </div>

    <div id="videos">
      <div>
        <div>Local</div>
        <video id="localVideo" autoplay playsinline muted></video>
      </div>
    </div>

    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <script>
      const pcConfig = { iceServers: [ { urls: 'stun:stun.l.google.com:19302' } ] };

      const socket = io();
      let localStream = null;
      let localVideo = document.getElementById('localVideo');
      let peers = {}; // sid -> { pc, videoEl }
      let mySid = null;

      document.getElementById('joinBtn').onclick = async () => {
        const name = document.getElementById('name').value || 'User';
        const room = document.getElementById('room').value || 'test';
        await startLocalStream();
        socket.emit('join', { room, name });
        document.getElementById('joinBtn').disabled = true;
        document.getElementById('leaveBtn').disabled = false;
      };

      document.getElementById('leaveBtn').onclick = () => {
        socket.emit('leave');
        cleanupAllPeers();
        if (localStream) {
          localStream.getTracks().forEach(t => t.stop());
          localStream = null;
          localVideo.srcObject = null;
        }
        document.getElementById('joinBtn').disabled = false;
        document.getElementById('leaveBtn').disabled = true;
      };

      async function startLocalStream(){
        try {
          localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
          localVideo.srcObject = localStream;
        } catch (e) {
          alert('Error accessing camera/microphone: ' + e);
          throw e;
        }
      }

      socket.on('connect', () => {
        console.log('socket connected');
        mySid = socket.id;
      });

      socket.on('joined', (data) => {
        // data: { peers: [{sid, name}, ...], you: {sid, name}, room }
        console.log('joined', data);
        mySid = data.you.sid;
        // Create peer connections to existing peers and initiate offers
        for (const p of data.peers) {
          createPeerAndOffer(p.sid);
        }
      });

      socket.on('new-participant', (data) => {
        // someone else joined after us
        console.log('new participant', data);
        createPeerAndOffer(data.sid);
      });

      socket.on('participant-left', (data) => {
        console.log('left', data);
        removePeer(data.sid);
      });

      socket.on('signal', async (data) => {
        // data: { from, to, signal }
        const from = data.from;
        const sig = data.signal;
        // If we don't have a pc for this peer yet, create it (answerer path)
        if (!peers[from]) {
          await createPeerAsAnswer(from);
        }
        const pc = peers[from].pc;
        if (sig.type === 'offer') {
          await pc.setRemoteDescription(new RTCSessionDescription(sig));
          const answer = await pc.createAnswer();
          await pc.setLocalDescription(answer);
          socket.emit('signal', { to: from, signal: pc.localDescription });
        } else if (sig.type === 'answer') {
          await pc.setRemoteDescription(new RTCSessionDescription(sig));
        } else if (sig.candidate) {
          try {
            await pc.addIceCandidate(sig);
          } catch (e) {
            console.warn('Error adding ICE candidate', e);
          }
        }
      });

      function createVideoElForPeer(sid) {
        const videosDiv = document.getElementById('videos');
        const wrap = document.createElement('div');
        wrap.id = 'wrap-' + sid;
        const label = document.createElement('div');
        label.innerText = 'Peer: ' + sid;
        const video = document.createElement('video');
        video.autoplay = true;
        video.playsInline = true;
        wrap.appendChild(label);
        wrap.appendChild(video);
        videosDiv.appendChild(wrap);
        return video;
      }

      async function createPeerAndOffer(sid) {
        if (sid === mySid) return;
        if (peers[sid]) return; // already exists
        console.log('createPeerAndOffer', sid);
        const pc = new RTCPeerConnection(pcConfig);
        const videoEl = createVideoElForPeer(sid);
        peers[sid] = { pc, videoEl };

        // add local tracks
        if (localStream) {
          for (const track of localStream.getTracks()) {
            pc.addTrack(track, localStream);
          }
        }

        pc.onicecandidate = (e) => {
          if (e.candidate) {
            socket.emit('signal', { to: sid, signal: e.candidate });
          }
        };

        pc.ontrack = (e) => {
          // attach remote stream
          videoEl.srcObject = e.streams[0];
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        socket.emit('signal', { to: sid, signal: pc.localDescription });
      }

      async function createPeerAsAnswer(sid) {
        console.log('createPeerAsAnswer', sid);
        const pc = new RTCPeerConnection(pcConfig);
        const videoEl = createVideoElForPeer(sid);
        peers[sid] = { pc, videoEl };

        if (localStream) {
          for (const track of localStream.getTracks()) {
            pc.addTrack(track, localStream);
          }
        }

        pc.onicecandidate = (e) => {
          if (e.candidate) {
            socket.emit('signal', { to: sid, signal: e.candidate });
          }
        };

        pc.ontrack = (e) => {
          videoEl.srcObject = e.streams[0];
        };

        return pc;
      }

      function removePeer(sid) {
        const entry = peers[sid];
        if (!entry) return;
        try { entry.pc.close(); } catch (e) {}
        const wrap = document.getElementById('wrap-' + sid);
        if (wrap) wrap.remove();
        delete peers[sid];
      }

      function cleanupAllPeers(){
        for (const sid of Object.keys(peers)) removePeer(sid);
      }

    </script>
  </body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@socketio.on('join')
def handle_join(data):
    room = data.get('room')
    name = data.get('name') or 'Anonymous'
    sid = request.sid
    if not room:
        emit('error', {'error': 'no room specified'})
        return

    # create room mapping
    if room not in ROOMS:
        ROOMS[room] = {}
    # prepare list of existing peers
    existing = [{'sid': s, 'name': ROOMS[room][s]['name']} for s in ROOMS[room].keys()]

    # add this user
    ROOMS[room][sid] = {'name': name}
    join_room(room)

    # notify the joining client about existing peers and itself
    emit('joined', { 'peers': existing, 'you': {'sid': sid, 'name': name}, 'room': room })

    # notify others in room about new participant
    emit('new-participant', {'sid': sid, 'name': name}, room=room, include_self=False)

@socketio.on('leave')
def handle_leave():
    sid = request.sid
    # find room containing sid
    for room, members in list(ROOMS.items()):
        if sid in members:
            name = members[sid]['name']
            leave_room(room)
            del members[sid]
            emit('participant-left', {'sid': sid, 'name': name}, room=room)
            if len(members) == 0:
                del ROOMS[room]
            break

@socketio.on('disconnect')
def handle_disconnect():
    # same as leave
    sid = request.sid
    for room, members in list(ROOMS.items()):
        if sid in members:
            name = members[sid]['name']
            leave_room(room)
            del members[sid]
            emit('participant-left', {'sid': sid, 'name': name}, room=room)
            if len(members) == 0:
                del ROOMS[room]
            break

@socketio.on('signal')
def handle_signal(data):
    # forward a signaling message to target
    to = data.get('to')
    signal = data.get('signal')
    from_sid = request.sid
    if not to or not signal:
        return
    # send to target only
    emit('signal', {'from': from_sid, 'signal': signal}, room=to)

if __name__ == '__main__':
    print('Starting Flask WebRTC demo on http://0.0.0.0:5000')
    socketio.run(app, host='0.0.0.0', port=5000)
