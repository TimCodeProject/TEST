from flask import Flask, render_template_string

app = Flask(__name__)

HTML = '''
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>WebRTC P2P — аудио чат</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 text-gray-900 p-6 font-sans">
  <div class="max-w-3xl mx-auto">
    <h1 class="text-3xl font-bold mb-4">WebRTC P2P — аудио чат</h1>
    <p class="text-gray-600 mb-6">Один HTML-файл через Flask. Откройте на двух устройствах. Обмен SDP и ICE вручную.</p>

    <div class="bg-white p-4 rounded-lg shadow mb-6">
      <h2 class="text-xl font-semibold mb-2">Аудио поток</h2>
      <audio id="remoteAudio" autoplay></audio>
      <div class="mt-3 flex gap-2">
        <button id="startBtn" class="px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600">Включить микрофон</button>
        <button id="hangupBtn" disabled class="px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600">Отключить</button>
      </div>
    </div>

    <div class="bg-white p-4 rounded-lg shadow">
      <h2 class="text-xl font-semibold mb-2">Инструкция</h2>
      <ol class="list-decimal list-inside text-gray-700 mb-4">
        <li>Нажмите «Включить микрофон» на обеих сторонах.</li>
        <li>На стороне A нажмите «Создать Offer», скопируйте Local SDP и отправьте стороне B.</li>
        <li>На стороне B вставьте Offer в Remote SDP, нажмите «Создать Answer» и отправьте Local SDP обратно стороне A.</li>
        <li>На стороне A вставьте Answer в Remote SDP и нажмите «Установить удалённое описание».</li>
        <li>ICE-кандидаты: копируйте Local ICE и вставляйте в Remote ICE у партнёра, затем «Добавить удалённые кандидаты».</li>
        <li>После успешного обмена аудио будет слышно.</li>
      </ol>

      <div class="flex flex-wrap gap-2 mb-3">
        <button id="createOfferBtn" disabled class="px-3 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">Создать Offer</button>
        <button id="createAnswerBtn" disabled class="px-3 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">Создать Answer</button>
        <button id="setRemoteDescBtn" disabled class="px-3 py-2 bg-purple-500 text-white rounded hover:bg-purple-600">Установить удалённое описание</button>
      </div>

      <label class="block mb-1 font-medium">Local SDP</label>
      <textarea id="localSDP" readonly class="w-full h-24 p-2 border rounded mb-3 bg-gray-100"></textarea>

      <label class="block mb-1 font-medium">Remote SDP</label>
      <textarea id="remoteSDP" class="w-full h-24 p-2 border rounded mb-3"></textarea>

      <div class="flex gap-2 mb-3">
        <button id="copyLocalSDP" class="px-3 py-2 bg-gray-700 text-white rounded hover:bg-gray-800">Скопировать Local SDP</button>
        <button id="pasteRemoteSDP" class="px-3 py-2 bg-gray-700 text-white rounded hover:bg-gray-800">Вставить Remote SDP</button>
      </div>

      <h3 class="text-lg font-semibold mb-1">ICE-кандидаты</h3>
      <label class="block mb-1 font-medium">Local ICE</label>
      <textarea id="localICE" readonly class="w-full h-24 p-2 border rounded mb-3 bg-gray-100"></textarea>

      <label class="block mb-1 font-medium">Remote ICE</label>
      <textarea id="remoteICE" class="w-full h-24 p-2 border rounded mb-3"></textarea>
      <button id="addRemoteICEBtn" class="px-3 py-2 bg-indigo-500 text-white rounded hover:bg-indigo-600">Добавить удалённые кандидаты</button>
    </div>
  </div>

  <script>
    let pc = null;
    let localStream = null;
    const configuration = {iceServers: [{urls: 'stun:stun.l.google.com:19302'}]};

    const remoteAudio = document.getElementById('remoteAudio');
    const startBtn = document.getElementById('startBtn');
    const hangupBtn = document.getElementById('hangupBtn');
    const createOfferBtn = document.getElementById('createOfferBtn');
    const createAnswerBtn = document.getElementById('createAnswerBtn');
    const setRemoteDescBtn = document.getElementById('setRemoteDescBtn');

    const localSDP = document.getElementById('localSDP');
    const remoteSDP = document.getElementById('remoteSDP');
    const localICE = document.getElementById('localICE');
    const remoteICE = document.getElementById('remoteICE');
    const addRemoteICEBtn = document.getElementById('addRemoteICEBtn');

    startBtn.onclick = async () => {
      try {
        localStream = await navigator.mediaDevices.getUserMedia({audio:true});
        startBtn.disabled = true;
        hangupBtn.disabled = false;
        createOfferBtn.disabled = false;
        createAnswerBtn.disabled = false;
        alert('Микрофон включён');
      } catch(e){ alert('Не удалось получить доступ к микрофону: ' + e.message); }
    };

    hangupBtn.onclick = () => {
      if(pc) pc.close();
      pc = null;
      if(localStream) localStream.getTracks().forEach(t=>t.stop());
      localStream = null;
      remoteAudio.srcObject = null;
      startBtn.disabled = false;
      hangupBtn.disabled = true;
      createOfferBtn.disabled = true;
      createAnswerBtn.disabled = true;
      localSDP.value = '';
      localICE.value = '';
      remoteSDP.value = '';
      remoteICE.value = '';
    };

    function createPeerConnection(){
      pc = new RTCPeerConnection(configuration);
      pc.onicecandidate = ev => { if(ev.candidate) localICE.value += JSON.stringify(ev.candidate)+'\n'; };
      pc.ontrack = ev => remoteAudio.srcObject = ev.streams[0];
      if(localStream) localStream.getTracks().forEach(track => pc.addTrack(track, localStream));
      return pc;
    }

    createOfferBtn.onclick = async () => {
      try {
        createPeerConnection();
        const dc = pc.createDataChannel('chat');
        dc.onopen = ()=>console.log('data channel open');
        dc.onmessage = e=>console.log('dc msg', e.data);

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        localSDP.value = JSON.stringify(pc.localDescription);
        setRemoteDescBtn.disabled = false;
      } catch(e){ alert('Ошибка при создании Offer: '+e.message); }
    };

    createAnswerBtn.onclick = async () => {
      try{
        const remoteVal = remoteSDP.value.trim();
        if(!remoteVal){ alert('Вставьте Offer в Remote SDP'); return; }
        const remoteDesc = JSON.parse(remoteVal);
        createPeerConnection();
        await pc.setRemoteDescription(remoteDesc);
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        localSDP.value = JSON.stringify(pc.localDescription);
        setRemoteDescBtn.disabled = false;
      } catch(e){ alert('Ошибка при создании Answer: '+e.message); }
    };

    setRemoteDescBtn.onclick = async () => {
      try{
        const remoteVal = remoteSDP.value.trim();
        if(!remoteVal){ alert('Вставьте SDP от партнёра'); return; }
        const remoteDesc = JSON.parse(remoteVal);
        if(!pc) createPeerConnection();
        await pc.setRemoteDescription(remoteDesc);
        alert('Удалённое описание установлено');
      } catch(e){ alert('Ошибка при установке удалённого описания: '+e.message); }
    };

    addRemoteICEBtn.onclick = async () => {
      const text = remoteICE.value.trim();
      if(!text){ alert('Вставьте хотя бы один кандидат'); return; }
      const lines = text.split(/\r?\n/).map(l=>l.trim()).filter(Boolean);
      for(const line of lines){
        try{
          const cand = JSON.parse(line);
          if(!pc) createPeerConnection();
          await pc.addIceCandidate(cand);
        } catch(e){ console.error('Ошибка добавления кандидата:', e); alert('Смотрите консоль'); }
      }
      remoteICE.value='';
    };

    document.getElementById('copyLocalSDP').onclick = async ()=>{ await navigator.clipboard.writeText(localSDP.value); alert('Local SDP скопирован'); };
    document.getElementById('pasteRemoteSDP').onclick = async ()=>{
      try{ remoteSDP.value = await navigator.clipboard.readText(); alert('Вставлено из буфера'); } catch(e){ alert('Не удалось прочитать буфер обмена: '+e.message); }
    };
  </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
