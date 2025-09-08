"""
Single-file demo: simple "walkie-talkie" mode using Flask + polling.
Adapted for free hosting (e.g. Render free plan). No WebRTC, no WebSockets.

Concept:
- Only one user speaks at a time (push-to-talk button).
- When "Talk" is pressed, the browser records small audio chunks and uploads them to the server.
- When "Listen" is active, the browser polls server and plays new chunks from other users.

Latency ~0.5-1.5s depending on polling interval.
Audio only.

To run locally:
1) pip install flask
2) python webrtc_flask_app.py
3) open http://localhost:5000

To deploy on Render:
- requirements.txt: Flask, gunicorn
- Start command: gunicorn webrtc_flask_app:app
"""

from flask import Flask, request, render_template_string, jsonify
from threading import Thread, Lock
import base64, time

app = Flask(__name__)

ROOMS = {}
ROOMS_LOCK = Lock()
MAX_CHUNKS_PER_ROOM = 400
CHUNK_RETENTION_SECONDS = 30

INDEX_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Flask Walkie-Talkie Demo</title>
  <style>
    body { font-family: Arial; margin: 12px }
    #controls { margin-bottom: 12px }
    #remote { margin-top: 10px }
    button { margin-right: 6px }
  </style>
</head>
<body>
  <h2>Walkie-Talkie Mode (Flask + polling)</h2>
  <div id="controls">
    Name: <input id="name" value="User" />
    Room: <input id="room" value="test" />
    <button id="talk">Hold to Talk</button>
    <button id="listen">Start Listening</button>
    <button id="stop">Stop</button>
    <div id="status"></div>
  </div>
  <div id="remote"></div>

  <script>
    let mediaStream = null;
    let recorder = null;
    let listenTimer = null;
    let lastTs = 0;
    const cid = Date.now().toString(36) + Math.random().toString(36).slice(2);

    function log(msg){ document.getElementById('status').innerText = msg; }

    document.getElementById('talk').onmousedown = startTalk;
    document.getElementById('talk').ontouchstart = startTalk;
    document.getElementById('talk').onmouseup = stopTalk;
    document.getElementById('talk').ontouchend = stopTalk;

    document.getElementById('listen').onclick = startListening;
    document.getElementById('stop').onclick = stopAll;

    async function startTalk(){
      const name = document.getElementById('name').value || 'User';
      const room = document.getElementById('room').value || 'test';
      try{
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio:true });
      }catch(e){ alert('Mic error: '+e); return; }
      let mime = '';
      if(MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) mime='audio/webm;codecs=opus';
      try{ recorder = new MediaRecorder(mediaStream, mime?{mimeType:mime}:{}) }
      catch(e){ recorder = new MediaRecorder(mediaStream) }
      recorder.ondataavailable = async (evt)=>{
        if(evt.data && evt.data.size>0){
          const fd = new FormData();
          fd.append('room', room);
          fd.append('user', name);
          fd.append('cid', cid);
          fd.append('blob', evt.data, 'chunk.webm');
          try{ await fetch('/upload', {method:'POST', body:fd}); }catch(err){console.error(err)}
        }
      };
      recorder.start(500);
      log('Talking... hold the button');
    }

    function stopTalk(){
      if(recorder){ try{recorder.stop();}catch(e){} recorder=null; }
      if(mediaStream){ mediaStream.getTracks().forEach(t=>t.stop()); mediaStream=null; }
      log('Stopped talking');
    }

    function startListening(){
      const room = document.getElementById('room').value || 'test';
      lastTs=0;
      if(listenTimer) clearInterval(listenTimer);
      listenTimer=setInterval(async()=>{
        try{
          const res=await fetch('/poll?room='+encodeURIComponent(room)+'&since='+lastTs);
          if(!res.ok) return;
          const j=await res.json();
          for(const c of j.chunks){
            if(c.cid===cid) continue;
            if(c.ts<=lastTs) continue;
            lastTs=Math.max(lastTs, c.ts);
            const bytes=Uint8Array.from(atob(c.data),ch=>ch.charCodeAt(0));
            const blob=new Blob([bytes.buffer],{type:c.mime});
            const url=URL.createObjectURL(blob);
            const audio=new Audio(url);
            audio.play();
            setTimeout(()=>{URL.revokeObjectURL(url)},5000);
          }
        }catch(e){console.error(e)}
      },1000);
      log('Listening...');
    }

    function stopAll(){
      stopTalk();
      if(listenTimer){ clearInterval(listenTimer); listenTimer=null; }
      log('Stopped');
    }
  </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/upload', methods=['POST'])
def upload():
    room=request.form.get('room'); user=request.form.get('user') or 'Anonymous'; cid=request.form.get('cid') or ''
    if not room: return jsonify({'error':'no room'}),400
    data=None; mime='audio/webm'
    if 'blob' in request.files:
        f=request.files['blob']; data=f.read(); mime=f.mimetype or mime
    if not data: return jsonify({'error':'no data'}),400
    chunk={'ts':time.time(),'user':user,'cid':cid,'mime':mime,'data':data}
    with ROOMS_LOCK:
        if room not in ROOMS: ROOMS[room]=[]
        ROOMS[room].append(chunk)
        if len(ROOMS[room])>MAX_CHUNKS_PER_ROOM:
            ROOMS[room]=ROOMS[room][-MAX_CHUNKS_PER_ROOM:]
    return jsonify({'ok':True})

@app.route('/poll')
def poll():
    room=request.args.get('room'); since=float(request.args.get('since') or 0)
    if not room: return jsonify({'error':'no room'}),400
    out=[]
    with ROOMS_LOCK:
        if room in ROOMS:
            for c in ROOMS[room]:
                if c['ts']>since:
                    out.append({'ts':c['ts'],'user':c['user'],'cid':c['cid'],'mime':c['mime'],'data':base64.b64encode(c['data']).decode('ascii')})
    return jsonify({'chunks':out,'now':time.time()})

def cleaner():
    while True:
        with ROOMS_LOCK:
            for r in list(ROOMS.keys()):
                ROOMS[r]=[c for c in ROOMS[r] if time.time()-c['ts']<=CHUNK_RETENTION_SECONDS]
                if not ROOMS[r]: del ROOMS[r]
        time.sleep(3)

Thread(target=cleaner,daemon=True).start()

if __name__=='__main__':
    app.run(host='0.0.0.0',port=5000,debug=True)
