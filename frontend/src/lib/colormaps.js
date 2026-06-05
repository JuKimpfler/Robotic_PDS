export function interpolateColor(color1, color2, factor) {
  factor = Math.max(0, Math.min(1, factor));
  
  const parseColor = (hex) => {
    let clean = hex.trim();
    if (clean.startsWith('#')) clean = clean.substring(1);
    if (clean.length === 3) {
      clean = clean.split('').map(c => c + c).join('');
    }
    return {
      r: parseInt(clean.substring(0, 2), 16) || 0,
      g: parseInt(clean.substring(2, 4), 16) || 0,
      b: parseInt(clean.substring(4, 6), 16) || 0,
    };
  };

  const c1 = parseColor(color1);
  const c2 = parseColor(color2);

  const r = Math.round(c1.r + factor * (c2.r - c1.r));
  const g = Math.round(c1.g + factor * (c2.g - c1.g));
  const b = Math.round(c1.b + factor * (c2.b - c1.b));

  const toHex = (n) => {
    const h = n.toString(16);
    return h.length === 1 ? '0' + h : h;
  };

  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}
