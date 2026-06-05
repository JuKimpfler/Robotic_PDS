import { decode } from '@msgpack/msgpack';
import { channelMap, updateLiveValues } from '../stores/channelData.js';
import { paramDefinitions } from '../stores/params.js';
import { wsConnected, frameRate, latency, dropped, rpiIp, hotspotState } from '../stores/connection.js';

let socket = null;
let reconnectDelay = 1000;
const maxReconnectDelay = 10000;

/** WebSocket URL per §3.3 / GUI.7 — port 9001 in production, Vite proxy in dev. */
function wsUrl() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  if (import.meta.env.DEV) {
    return `${protocol}//${window.location.host}/stream`;
  }
  return `${protocol}//${window.location.hostname}:9001/stream`;
}

function dispatchJsonMessage(data) {
  switch (data.type) {
    case 'channel_map':
      channelMap.set(data.channels || []);
      break;
    case 'status':
      hotspotState.set(data.hotspot || 'off');
      rpiIp.set(data.rpi_ip || '—');
      dropped.set(data.frames_dropped || 0);
      if (data.rate_hz) frameRate.set(data.rate_hz);
      break;
    case 'param_map':
      paramDefinitions.set(data.params || []);
      break;
    case 'frame':
      handleFrame(data);
      break;
    default:
      break;
  }
}

function handleFrame(data) {
  const values = data.values instanceof Float32Array
    ? data.values
    : new Float32Array(data.values || []);

  updateLiveValues(values);
  if (data.rate_hz) frameRate.set(data.rate_hz);

  const simulatedLatency = 0.4 + Math.random() * 0.4;
  latency.set(parseFloat(simulatedLatency.toFixed(2)));

  window.dispatchEvent(new CustomEvent('telemetry-frame', { detail: data }));
}

export function connect() {
  const url = wsUrl();
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
    // JSON text frames: channel_map, status, param_map
    if (typeof event.data === 'string') {
      try {
        dispatchJsonMessage(JSON.parse(event.data));
      } catch (e) {
        console.error('Failed to parse JSON WS message:', e);
      }
      return;
    }

    if (event.data instanceof ArrayBuffer) {
      const payload = new Uint8Array(event.data);

      // Try JSON first (some proxies may deliver text as ArrayBuffer)
      try {
        const text = new TextDecoder().decode(payload);
        if (text.startsWith('{')) {
          dispatchJsonMessage(JSON.parse(text));
          return;
        }
      } catch {
        // not JSON — fall through to MessagePack
      }

      try {
        const data = decode(payload);
        if (data.type === 'frame' || data.values) {
          handleFrame(data);
        } else if (data.type) {
          dispatchJsonMessage(data);
        }
      } catch (e) {
        console.error('Failed to decode MessagePack frame:', e);
      }
    }
  };
}
