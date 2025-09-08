<script>
const socket = io();
let localStream;
let peers = {};
let myId = null;
let roomId = null;

const config = { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] };

async function startMedia() {
  localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
  document.getElementById("localVideo").srcObject = localStream;
}

async function createPeerConnection(peerId, isOfferer) {
  if (peers[peerId]) return peers[peerId];
  const pc = new RTCPeerConnection(config);
  peers[peerId] = pc;

  // добавить локальные треки
  localStream.getTracks().forEach(t => pc.addTrack(t, localStream));

  // принимать треки
  pc.ontrack = e => {
    let vid = document.getElementById("v_" + peerId);
    if (!vid) {
      const container = document.createElement("div");
      container.className = "bg-black rounded overflow-hidden";
      vid = document.createElement("video");
      vid.id = "v_" + peerId;
      vid.autoplay = true;
      vid.playsInline = true;
      vid.className = "w-full h-40 object-cover";
      container.appendChild(vid);
      document.getElementById("videos").appendChild(container);
    }
    vid.srcObject = e.streams[0];
  };

  pc.onicecandidate = e => {
    if (e.candidate) socket.emit("signal", { to: peerId, candidate: e.candidate });
  };

  if (isOfferer) {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    socket.emit("signal", { to: peerId, sdp: pc.localDescription });
  }

  return pc;
}

document.getElementById("joinBtn").onclick = async () => {
  roomId = document.getElementById("roomInput").value || "demo";
  await startMedia();
  socket.emit("join", { room: roomId });
  document.getElementById("joinBtn").classList.add("hidden");
  document.getElementById("leaveBtn").classList.remove("hidden");
};

document.getElementById("leaveBtn").onclick = () => {
  socket.emit("leave", { room: roomId });
  for (let id in peers) peers[id].close();
  peers = {};
  // оставить только local video
  const videos = document.getElementById("videos");
  videos.innerHTML = `
    <div class="bg-black rounded overflow-hidden relative">
      <video id="localVideo" autoplay muted playsinline class="w-full h-64 object-cover"></video>
      <div class="absolute bottom-2 left-2 bg-black/40 text-white px-2 py-1 rounded text-sm">Вы</div>
    </div>`;
  if (localStream) document.getElementById("localVideo").srcObject = localStream;
  document.getElementById("joinBtn").classList.remove("hidden");
  document.getElementById("leaveBtn").classList.add("hidden");
};

// Сигналы
socket.on("peers", async data => {
  myId = data.you;
  for (const id of data.peers) {
    await createPeerConnection(id, true);
  }
});

socket.on("peer-joined", async data => {
  await createPeerConnection(data.id, true);
});

socket.on("signal", async data => {
  const from = data.from;
  let pc = peers[from];
  if (!pc) pc = await createPeerConnection(from, false);

  if (data.sdp) {
    await pc.setRemoteDescription(new RTCSessionDescription(data.sdp));
    if (data.sdp.type === "offer") {
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      socket.emit("signal", { to: from, sdp: pc.localDescription });
    }
  }
  if (data.candidate) {
    try { await pc.addIceCandidate(new RTCIceCandidate(data.candidate)); } catch(e){}
  }

  if (data.broadcast && data.chat) {
    const box = document.getElementById("chatBox");
    box.innerHTML += `<div><b>Участник:</b> ${data.chat}</div>`;
  }
});

socket.on("peer-left", data => {
  const id = data.id;
  if (peers[id]) peers[id].close();
  delete peers[id];
  const el = document.getElementById("v_" + id);
  if (el) el.remove();
});

// Чат
document.getElementById("sendBtn").onclick = () => {
  const msg = document.getElementById("chatInput").value;
  if (!msg) return;
  const box = document.getElementById("chatBox");
  box.innerHTML += `<div><b>Вы:</b> ${msg}</div>`;
  document.getElementById("chatInput").value = "";
  socket.emit("signal", { broadcast: true, chat: msg });
};
</script>
