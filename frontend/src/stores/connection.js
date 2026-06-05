import { writable } from 'svelte/store';

export const wsConnected = writable(false);
export const frameRate = writable(0);
export const latency = writable(0);
export const dropped = writable(0);
export const rpiIp = writable('—');
export const hotspotState = writable('off'); // 'on' | 'off' | 'transitioning'
export const wsClientsCount = writable(0);
