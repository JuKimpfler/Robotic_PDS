import { writable } from 'svelte/store';

export const paramDefinitions = writable([]);
export const dirtyParams = writable({}); // map of index -> temporary edited value
export const presets = writable([]);
