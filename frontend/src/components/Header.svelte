<script>
  import { wsConnected, frameRate, latency, dropped, rpiIp, hotspotState } from '../stores/connection.js';
  import StatusBadge from './StatusBadge.svelte';
  import { Wifi, Activity, AlertCircle, RefreshCw } from 'lucide-svelte';

  let hotspotBusy = false;

  async function toggleHotspot() {
    if (hotspotBusy) return;
    hotspotBusy = true;

    const current = $hotspotState;
    // optimistictally show transitioning
    hotspotState.set('transitioning');

    const endpoint = current === 'on' ? '/api/hotspot/stop' : '/api/hotspot/start';
    try {
      const res = await fetch(endpoint, { method: 'POST' });
      if (!res.ok) {
        throw new Error(await res.text());
      }
      // Status will be updated via WebSocket status frames
    } catch (e) {
      console.error('Failed to toggle hotspot:', e);
      alert('Hotspot toggle error: ' + e.message);
      // Revert status
      hotspotState.set(current);
    } finally {
      hotspotBusy = false;
    }
  }
</script>

<header class="w-full bg-slate-950/80 backdrop-blur-md border-b border-slate-900 px-6 py-4 flex flex-col md:flex-row items-center justify-between gap-4 sticky top-0 z-50">
  <!-- Brand logo -->
  <div class="flex items-center gap-3">
    <div class="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center font-bold text-white shadow-lg shadow-blue-500/20 font-display">
      A
    </div>
    <div>
      <h1 class="text-lg font-bold tracking-tight font-display bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
        Antigravity Telemetry
      </h1>
      <p class="text-xs text-slate-500 font-mono">PDS Control Platform v0.3</p>
    </div>
  </div>

  <!-- Stats Grid -->
  <div class="flex flex-wrap items-center gap-3 md:gap-6 text-sm">
    <!-- WebSocket connection -->
    <StatusBadge status={$wsConnected}>
      <span class="text-slate-400 font-medium">WebSocket:</span>
      <span class="font-mono font-semibold text-slate-100">
        {$wsConnected ? 'Verbunden' : 'Getrennt'}
      </span>
    </StatusBadge>

    <!-- Source RPi IP -->
    <div class="flex items-center gap-1.5 px-3 py-1 bg-slate-900 border border-slate-800 rounded-lg text-slate-300">
      <span class="text-xs text-slate-500 uppercase font-mono">RPi IP:</span>
      <span class="font-mono text-xs font-medium text-slate-100">{$rpiIp}</span>
    </div>

    <!-- Hotspot Control -->
    <button
      on:click={toggleHotspot}
      disabled={hotspotBusy || $hotspotState === 'transitioning'}
      class="flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold cursor-pointer transition-all duration-300"
      class:bg-blue-600={$hotspotState === 'off'}
      class:border-blue-500={$hotspotState === 'off'}
      class:text-white={$hotspotState === 'off'}
      class:bg-slate-900={$hotspotState === 'on'}
      class:border-slate-800={$hotspotState === 'on'}
      class:text-rose-400={$hotspotState === 'on'}
      class:opacity-50={hotspotBusy || $hotspotState === 'transitioning'}
    >
      <Wifi class="w-3.5 h-3.5" />
      <span>Hotspot: {$hotspotState === 'on' ? 'Ausschalten' : 'Einschalten'}</span>
      <span
        class="w-1.5 h-1.5 rounded-full"
        class:bg-emerald-500={$hotspotState === 'on'}
        class:bg-rose-500={$hotspotState === 'off'}
        class:bg-amber-500={$hotspotState === 'transitioning'}
        class:pulse-glow={$hotspotState === 'on' || $hotspotState === 'transitioning'}
      ></span>
    </button>

    <!-- Live Performance stats -->
    <div class="flex items-center gap-4 border-l border-slate-800 pl-4 md:pl-6">
      <div class="flex flex-col">
        <span class="text-[10px] text-slate-500 uppercase font-mono tracking-wider">Messrate</span>
        <div class="flex items-center gap-1 text-slate-200">
          <Activity class="w-3.5 h-3.5 text-blue-400" />
          <span class="font-mono text-sm font-semibold">{$frameRate.toFixed(1)} Hz</span>
        </div>
      </div>

      <div class="flex flex-col">
        <span class="text-[10px] text-slate-500 uppercase font-mono tracking-wider">Latenz</span>
        <div class="flex items-center gap-1 text-slate-200">
          <RefreshCw class="w-3.5 h-3.5 text-emerald-400" />
          <span class="font-mono text-sm font-semibold">{$latency} ms</span>
        </div>
      </div>

      <div class="flex flex-col">
        <span class="text-[10px] text-slate-500 uppercase font-mono tracking-wider">Verworfen</span>
        <div class="flex items-center gap-1 text-slate-200">
          <AlertCircle class="w-3.5 h-3.5 text-rose-400" />
          <span class="font-mono text-sm font-semibold text-rose-300">{$dropped}</span>
        </div>
      </div>
    </div>
  </div>
</header>
