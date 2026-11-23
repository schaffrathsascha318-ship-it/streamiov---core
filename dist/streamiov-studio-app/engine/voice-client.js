'use strict';

const MAX_PEERS = 7;

/**
 * Peer-to-peer WebRTC voice mesh. Signalling carries only SDP/ICE and
 * participant state; audio media travels through DTLS-SRTP peer connections.
 */
class StreamiovVoiceClient {
  constructor({ websocketUrl, ticket, localStream, iceServers, onState, onParticipants, onRemoteStream } = {}) {
    if (typeof websocketUrl !== 'string' || !/^wss:\/\//i.test(websocketUrl)) {
      throw new TypeError('Voice signalling requires a secure wss:// endpoint.');
    }
    if (typeof ticket !== 'string' || !/^[A-Za-z0-9_-]{40,64}$/.test(ticket)) {
      throw new TypeError('A short-lived one-use Voice ticket is required.');
    }
    if (!localStream || typeof localStream.getAudioTracks !== 'function' || !localStream.getAudioTracks().some(track => track.readyState === 'live')) {
      throw new TypeError('A live processed microphone stream is required.');
    }
    this.websocketUrl = websocketUrl;
    this.ticket = ticket;
    this.localStream = localStream;
    this.iceServers = Array.isArray(iceServers) && iceServers.length ? iceServers : [{ urls: 'stun:stun.l.google.com:19302' }];
    this.onState = typeof onState === 'function' ? onState : () => {};
    this.onParticipants = typeof onParticipants === 'function' ? onParticipants : () => {};
    this.onRemoteStream = typeof onRemoteStream === 'function' ? onRemoteStream : () => {};
    this.socket = null;
    this.participantId = null;
    this.peers = new Map();
    this.participants = new Map();
    this.muted = false;
    this.deafened = false;
    this.pushToTalk = false;
    this.pushToTalkPressed = false;
    this.closed = false;
    this.heartbeat = null;
  }

  connect() {
    if (this.socket || this.closed) throw new Error('Voice client is already connected or closed.');
    const url = new URL(this.websocketUrl);
    url.searchParams.set('ticket', this.ticket);
    this.socket = new WebSocket(url.toString());
    this.socket.addEventListener('open', () => {
      this.onState({ state: 'signalling_connected' });
      this.heartbeat = setInterval(() => this.ping(), 25_000);
    });
    this.socket.addEventListener('message', event => {
      this.#handleMessage(event.data).catch(error => this.onState({ state: 'error', error: String(error.message || error) }));
    });
    this.socket.addEventListener('close', event => {
      if (this.heartbeat) clearInterval(this.heartbeat);
      this.heartbeat = null;
      this.#closePeers();
      this.onState({ state: 'disconnected', code: event.code, reason: event.reason });
    });
    this.socket.addEventListener('error', () => this.onState({ state: 'error', error: 'Voice-Signalisierung nicht erreichbar.' }));
    return this;
  }

  async #handleMessage(raw) {
    if (typeof raw !== 'string' || raw.length > 64 * 1024) throw new Error('Voice-Signalisierungsnachricht ist ungültig.');
    const message = JSON.parse(raw);
    if (message.type === 'ready') {
      this.participantId = message.participantId;
      this.participants.clear();
      for (const item of message.participants || []) {
        if (item.participantId === this.participantId) continue;
        this.participants.set(item.participantId, item);
      }
      this.#publishParticipants();
      this.onState({ state: 'connected', participantId: this.participantId, participantCount: this.participants.size + 1 });
      for (const peerId of this.participants.keys()) await this.#createOffer(peerId);
      return;
    }
    if (message.type === 'participant-joined') {
      if (message.participant?.participantId) {
        this.participants.set(message.participant.participantId, message.participant);
        this.#publishParticipants();
      }
      return;
    }
    if (message.type === 'participant-left') {
      const peerId = message.participantId;
      this.participants.delete(peerId);
      this.#dropPeer(peerId);
      this.#publishParticipants();
      return;
    }
    if (message.type === 'mute' || message.type === 'deafen' || message.type === 'speaking') {
      const participant = this.participants.get(message.participantId) || { participantId: message.participantId };
      participant[message.type] = message.value;
      this.participants.set(message.participantId, participant);
      this.#publishParticipants();
      return;
    }
    if (message.type === 'error') {
      this.onState({ state: 'signalling_error', code: message.code });
      return;
    }
    if (message.type === 'pong') return;
    if (!['offer', 'answer', 'ice'].includes(message.type) || typeof message.from !== 'string') return;
    const peer = this.#ensurePeer(message.from);
    if (message.type === 'offer') {
      await peer.connection.setRemoteDescription(message.payload);
      await this.#flushIce(peer);
      const answer = await peer.connection.createAnswer();
      await peer.connection.setLocalDescription(answer);
      this.#send({ type: 'answer', target: message.from, payload: peer.connection.localDescription });
    } else if (message.type === 'answer') {
      await peer.connection.setRemoteDescription(message.payload);
      await this.#flushIce(peer);
    } else if (message.type === 'ice') {
      const candidate = new RTCIceCandidate(message.payload);
      if (peer.connection.remoteDescription) await peer.connection.addIceCandidate(candidate);
      else peer.pendingIce.push(candidate);
    }
  }

  #ensurePeer(peerId) {
    let peer = this.peers.get(peerId);
    if (peer) return peer;
    if (this.peers.size >= MAX_PEERS) throw new Error('Maximale Anzahl direkter Voice-Verbindungen erreicht.');
    const connection = new RTCPeerConnection({ iceServers: this.iceServers });
    peer = { connection, pendingIce: [] };
    this.peers.set(peerId, peer);
    for (const track of this.localStream.getAudioTracks()) connection.addTrack(track, this.localStream);
    connection.addEventListener('icecandidate', event => {
      if (event.candidate) this.#send({ type: 'ice', target: peerId, payload: event.candidate.toJSON() });
    });
    connection.addEventListener('track', event => {
      event.track.enabled = !this.deafened;
      const stream = event.streams?.[0] || new MediaStream([event.track]);
      this.onRemoteStream({ participantId: peerId, stream });
    });
    connection.addEventListener('connectionstatechange', () => {
      this.onState({ state: 'peer_state', participantId: peerId, connectionState: connection.connectionState });
      if (['failed', 'closed'].includes(connection.connectionState)) this.#dropPeer(peerId);
    });
    return peer;
  }

  async #createOffer(peerId) {
    const peer = this.#ensurePeer(peerId);
    const offer = await peer.connection.createOffer();
    await peer.connection.setLocalDescription(offer);
    this.#send({ type: 'offer', target: peerId, payload: peer.connection.localDescription });
  }

  async #flushIce(peer) {
    const candidates = peer.pendingIce.splice(0);
    for (const candidate of candidates) await peer.connection.addIceCandidate(candidate);
  }

  #send(message) {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(message));
    return true;
  }

  #publishParticipants() {
    this.onParticipants([...this.participants.values()]);
  }

  #dropPeer(peerId) {
    const peer = this.peers.get(peerId);
    if (!peer) return;
    this.peers.delete(peerId);
    try { peer.connection.close(); } catch {}
    this.onRemoteStream({ participantId: peerId, stream: null, removed: true });
  }

  #closePeers() {
    for (const peerId of [...this.peers.keys()]) this.#dropPeer(peerId);
  }

  setMuted(value) {
    this.muted = Boolean(value);
    this.#applyLocalTrackState();
    this.#send({ type: 'mute', value: this.muted });
  }

  setPushToTalk(enabled) {
    this.pushToTalk = Boolean(enabled);
    this.#applyLocalTrackState();
  }

  setPushToTalkPressed(pressed) {
    this.pushToTalkPressed = Boolean(pressed);
    this.#applyLocalTrackState();
    this.#send({ type: 'speaking', value: !this.muted && (!this.pushToTalk || this.pushToTalkPressed) });
  }

  setDeafened(value) {
    this.deafened = Boolean(value);
    for (const peer of this.peers.values()) {
      for (const sender of peer.connection.getReceivers()) {
        if (sender.track) sender.track.enabled = !this.deafened;
      }
    }
    this.#send({ type: 'deafen', value: this.deafened });
  }

  #applyLocalTrackState() {
    const enabled = !this.muted && (!this.pushToTalk || this.pushToTalkPressed);
    for (const track of this.localStream.getAudioTracks()) track.enabled = enabled;
  }

  ping() { this.#send({ type: 'ping' }); }

  disconnect() {
    if (this.closed) return;
    this.closed = true;
    if (this.heartbeat) clearInterval(this.heartbeat);
    this.heartbeat = null;
    this.#send({ type: 'leave' });
    try { this.socket?.close(1000, 'client_disconnect'); } catch {}
    this.#closePeers();
    this.socket = null;
    this.onState({ state: 'disconnected' });
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = { StreamiovVoiceClient, MAX_PEERS };
if (typeof globalThis !== 'undefined') globalThis.StreamiovVoiceClient = StreamiovVoiceClient;
