"""
Single-file demo: lightweight "conference" using MediaRecorder + HTTP polling (no WebRTC, no WebSockets)
Adapted for Render free tier (one-file, simple POST/poll flow).

How it works (high level):
- Clients record short audio chunks via MediaRecorder (1s slices) and POST them to the server (/upload).
- Clients poll the server every second (/poll?room=...&since=...), receive new base64-encoded audio chunks from other participants and play them.
- Server keeps recent chunks in memory per room (short retention window) and forwards them to pollers.

Why this for Render free plan:
- Render free web services may suspend or disconnect long-lived sockets and have sleep/15-min inactivity behavior that makes WebSocket or persistent WebRTC signaling unreliable on the free plan. This HTTP POST+polling design uses normal short HTTP requests which work well with Render's web services. See Render docs and community threads for notes. (See notes below.)

Limitations:
- Not real-time like WebRTC. Expect ~0.5–1.5s latency depending on poll interval.
- Audio-only (no video) in this demo.
- Not production-ready: memory kept in RAM, no auth, no HTTPS handling here (Render handles TLS), limited size/caps.

To run locally:
1) pip install flask
2) python webrtc_flask_app.py
3) open http://localhost:5000

To deploy on Render:
- Put this file in a GitHub repo and add requirements.txt with at least `Flask` and `gunicorn`.
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn webrtc_flask_app:app`
- More: https://render.com/docs/deploy-flask

"""

from flask import Flask, request, render_template_string, jsonify
from threading import Lock, Thread
import base64
import time
import atexit

app = Flask(__name__)

# In-memory storage: { room: [ {ts, user, cid, mime, data_bytes}, ... ] }
ROOMS = {}
ROOMS_LOCK = Lock()

# Configuration caps
MAX_CHUNKS_PER_ROOM = 800            # max stored chunks per room
CHUNK_RETENTION_SECONDS = 30         # keep chunks for ~30s
POLL_INTERVAL_SECONDS = 1.0          # clients poll every ~1 second (client-side)

INDEX_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Polling-audio conference (Flask single file)</title>
  <style>
    body{font-family:Arial,Helvetica,sans-serif;margin:12px}
    #remote { margin-top:10px }
    .peer { margin-bottom:8px }
    audio { display:block; margin-top:4px }
  </style>
</head>
<body>
  <h2>Polling audio conference — lightweight demo</h2>
  <div>
    Name: <input id="name" value="User" />
    Room: <input id="room" value="test" />
    <button id="join">Join (start mic)</button>
    <button id="leave" disabled>Leave</button>
    <div id="status"></div>
  </div>

  <div id="remote"></div>

  <script>
    // tiny client that records 1s audio chunks and POSTs them
    let mediaStream = null;
    let recorder = null;
    let recording = false;
    let pollTimer = null;
    let lastTs = 0;
    const cid = (crypto && crypto.randomUUID) ? crypto.randomUUID() : (Date.now().toString(36) + Math.random().toString(36).slice(2));

    function log(s){ document.getElementById('status').innerText = s }

    document.getElementById('join').onclick = async () => {
      const name = document.getElementById('name').value || 'User';
      const room = document.getElementById('room').value || 'test';
      try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch(e){ alert('Cannot access microphone: '+e); return; }

      // choose a mime type that's supported
      let mime = '';
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) mime = 'audio/webm;codecs=opus';
      else if (MediaRecorder.isTypeSupported('audio/ogg')) mime = 'audio/ogg';

      try {
        recorder = new MediaRecorder(mediaStream, mime ? {mimeType: mime} : undefined );
      } catch(e){ recorder = new MediaRecorder(mediaStream); }

      recorder.ondataavailable = async (evt) => {
        if (!evt.data || evt.data.size === 0) return;
        // send chunk via POST
        try {
          const fd = new FormData();
          fd.append('room', room);
          fd.append('user', name);
          fd.append('cid', cid);
          fd.append('blob', evt.data, 'chunk.webm');
          await fetch('/upload', { method: 'POST', body: fd });
        } catch(e){ console.error('upload error', e); }
      };

      recorder.start(1000); // timeslice 1s
      recording = true;
      document.getElementById('join').disabled = true;
      document.getElementById('leave').disabled = false;
      log('Recording & uploading...');

      // start polling for remote chunks
      lastTs = 0;
      pollTimer = setInterval(async () => {
        try {
          const url = '/poll?room=' + encodeURIComponent(room) + '&since=' + encodeURIComponent(lastTs);
          const res = await fetch(url);
          if (!res.ok) return;
          const j = await res.json();
          for (const c of j.chunks){
            // skip our own chunks
            if (c.cid === cid) continue;
            if (c.ts <= lastTs) continue;
            lastTs = Math.max(lastTs, c.ts);
            // convert base64->blob
            const bytes = Uint8Array.from(atob(c.data), ch => ch.charCodeAt(0));
            const blob = new Blob([bytes.buffer], { type: c.mime });
            const url = URL.createObjectURL(blob);
            const container = document.createElement('div'); container.className='peer';
            const label = document.createElement('div'); label.innerText = c.user + ' — ' + new Date(c.ts*1000).toLocaleTimeString();
            const audio = document.createElement('audio'); audio.src = url; audio.autoplay = true; audio.controls = false;
            container.appendChild(label); container.appendChild(audio);
            document.getElementById('remote').prepend(container);
            // cleanup after a bit
            setTimeout(()=>{ try{ URL.revokeObjectURL(url); container.remove(); }catch(e){} }, 20000);
          }
        } catch(e){ console.error('poll error', e); }
      }, 1000);
    };

    document.getElementById('leave').onclick = () => {
      if (recorder && recording) {
        try { recorder.stop(); } catch(e) {}
      }
      if (mediaStream){ mediaStream.getTracks().forEach(t=>t.stop()); mediaStream = null; }
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      document.getElementById('join').disabled = false;
      document.getElementById('leave').disabled = true;
      log('Stopped');
    };
  </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/upload', methods=['POST'])
def upload():
    room = request.form.get('room')
    user = request.form.get('user') or 'Anonymous'
    cid = request.form.get('cid') or ''
    if not room:
        return jsonify({'error': 'no room specified'}), 400

    # accept uploaded file 'blob'
    data = None
    mime = 'audio/webm'
    if 'blob' in request.files:
        f = request.files['blob']
        data = f.read()
        mime = f.mimetype or mime
    else:
        # try raw JSON base64
        j = request.get_json(silent=True)
        if j and 'data' in j:
            data = base64.b64decode(j['data'])
            mime = j.get('mime', mime)

    if not data:
        return jsonify({'error': 'no blob data'}), 400

    chunk = {'ts': time.time(), 'user': user, 'cid': cid, 'mime': mime, 'data': data}
    with ROOMS_LOCK:
        if room not in ROOMS:
            ROOMS[room] = []
        ROOMS[room].append(chunk)
        # enforce cap
        if len(ROOMS[room]) > MAX_CHUNKS_PER_ROOM:
            ROOMS[room] = ROOMS[room][-MAX_CHUNKS_PER_ROOM:]
    return jsonify({'ok': True})

@app.route('/poll')
def poll():
    room = request.args.get('room')
    since = float(request.args.get('since') or 0)
    if not room:
        return jsonify({'error': 'no room specified'}), 400
    out = []
    with ROOMS_LOCK:
        if room in ROOMS:
            for c in ROOMS[room]:
                if c['ts'] > since:
                    out.append({'ts': c['ts'], 'user': c['user'], 'cid': c['cid'], 'mime': c['mime'], 'data': base64.b64encode(c['data']).decode('ascii')})
    return jsonify({'chunks': out, 'now': time.time()})

# background cleaner thread
def cleaner():
    while True:
        with ROOMS_LOCK:
            for room in list(ROOMS.keys()):
                ROOMS[room] = [c for c in ROOMS[room] if time.time() - c['ts'] <= CHUNK_RETENTION_SECONDS]
                if not ROOMS[room]:
                    del ROOMS[room]
        time.sleep(3)

cleaner_thread = Thread(target=cleaner, daemon=True)
cleaner_thread.start()

if __name__ == '__main__':
    # local debug server; in production use gunicorn: gunicorn webrtc_flask_app:app
    app.run(host='0.0.0.0', port=5000, debug=True)
