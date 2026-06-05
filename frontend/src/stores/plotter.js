import { writable } from 'svelte/store';

export const selectedChannels = writable([]); // array of channel indices (max 8)
export const plotterState = writable('STOPPED'); // 'STOPPED' | 'RUNNING' | 'PAUSED'
export const timeWindow = writable(10); // window size in seconds: 1, 5, 10, 30, 60, 120
