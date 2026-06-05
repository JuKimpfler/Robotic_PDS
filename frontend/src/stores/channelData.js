import { writable } from 'svelte/store';

export const channelMap = writable([]);
export const liveValues = writable(new Float32Array(1024));
export const minValues = writable(new Float32Array(1024).fill(Infinity));
export const maxValues = writable(new Float32Array(1024).fill(-Infinity));

export function resetMinMax() {
  minValues.update(arr => {
    arr.fill(Infinity);
    return arr;
  });
  maxValues.update(arr => {
    arr.fill(-Infinity);
    return arr;
  });
}

export function updateLiveValues(values) {
  liveValues.set(values);

  minValues.update(mins => {
    if (values.length > mins.length) {
      const newMuns = new Float32Array(values.length).fill(Infinity);
      newMuns.set(mins);
      mins = newMuns;
    }
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (Math.abs(v - 9898.0) > 0.01) { // Ignore dummy sentinel 9898.0
        if (mins[i] === Infinity || v < mins[i]) {
          mins[i] = v;
        }
      }
    }
    return mins;
  });

  maxValues.update(maxes => {
    if (values.length > maxes.length) {
      const newMaxes = new Float32Array(values.length).fill(-Infinity);
      newMaxes.set(maxes);
      maxes = newMaxes;
    }
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (Math.abs(v - 9898.0) > 0.01) { // Ignore dummy sentinel 9898.0
        if (maxes[i] === -Infinity || v > maxes[i]) {
          maxes[i] = v;
        }
      }
    }
    return maxes;
  });
}
