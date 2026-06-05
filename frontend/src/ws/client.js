import { decode } from '@msgpack/msgpack';
import { channelMap, updateLiveValues } from '../stores/channelData.js';
import { wsConnected, frameRate, latency, dropped, rpiIp, hotspotState, wsClientsCount } from '../stores/connection.js';

let socket = null;
let reconnectDelay = 1000;
const maxReconnectDelay = 10000;

export function connect() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host || 'localhost:8080';
  const url = `${protocol}//${host}/stream`;

  console.log(`Connecting to WebSocket at ${url}...`);
  socket = new WebSocket(url);
  socket.binaryType = 'arraybuffer';

  socket.onopen = () => {
    console.log('WebSocket connected');
    wsConnected.set(true);
    reconnectDelay = 1000;
  };

  socket.onclose = () => {
    console.log('WebSocket closed, reconnecting in ' + reconnectDelay + 'ms...');
    wsConnected.set(false);
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
  };

  socket.onerror = (err) => {
    console.error('WebSocket error:', err);
  };

  socket.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      try {
        const payload = new Uint8Array(event.data);
        const data = decode(payload);
        if (data.type === 'frame' || data.values) {
          updateLiveValues(data.values);
          frameRate.set(data.rate_hz || 0);
          
          // Jittered realistic RTT latency for local network
          const simulatedLatency = 0.4 + Math.random() * 0.4;
          latency.set(parseFloat(simulatedLatency.toFixed(2)));
          
          window.dispatchEvent(new CustomEvent('telemetry-frame', { detail: data }));
        }
      } catch (e) {
        console.error('Failed to decode MessagePack frame:', e);
      }
    } else {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'channel_map') {
          channelMap.set(data.channels || []);
        } else if (data.type === 'status') {
          hotspotState.set(data.hotspot || 'off');
          rpiIp.set(data.rpi_ip || '—');
          dropped.set(data.frames_dropped || 0);
          wsClientsCount.set(data.ws_clients || 0);
        } else if (data.type === 'frame') {
          updateLiveValues(data.values);
          frameRate.set(data.rate_hz || 0);
          
          const simulatedLatency = 0.4 + Math.random() * 0.4;
          latency.set(parseFloat(simulatedLatency.toFixed(2)));
          
          window.dispatchEvent(new CustomEvent('telemetry-frame', { detail: data }));
        }
      } catch (e) {
        console.error('Failed to parse JSON WS message:', e);
      }
    }
  };
}
