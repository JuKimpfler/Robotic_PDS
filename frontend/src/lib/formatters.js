import { DUMMY_VALUE } from './constants.js';

export function formatValue(val, precision = 2) {
  if (val === undefined || isNaN(val) || val === Infinity || val === -Infinity || Math.abs(val - DUMMY_VALUE) < 0.01) {
    return '—';
  }
  return val.toFixed(precision);
}
