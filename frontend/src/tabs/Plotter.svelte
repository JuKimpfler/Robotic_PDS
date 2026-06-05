<script>
  import { onMount } from 'svelte';
  import { channelMap } from '../stores/channelData.js';
  import { selectedChannels, plotterState, timeWindow } from '../stores/plotter.js';
  import ChannelSelector from '../components/ChannelSelector.svelte';
  import uPlotWrapper from '../components/uPlotWrapper.svelte';
  import { exportToCSV } from '../lib/csvExport.js';
  import { DUMMY_VALUE } from '../lib/constants.js';
  import { Play, Pause, Square, Download, ZoomIn, Info } from 'lucide-svelte';

  let channels = [];
  const unsubMap = channelMap.subscribe(val => { channels = val; });

  let buffer = [[]];
  let uplotOptions = {};
  let uplotData = [[]];

  const timeWindows = [1, 5, 10, 30, 60, 120];

  $: {
    const series = [{
      label: 'Zeit (s)',
      value: (self, rawValue) => rawValue !== null ? rawValue.toFixed(3) + 's' : '—'
    }];
    const data = [[]];

    $selectedChannels.forEach(idx => {
      const ch = channels[idx];
      if (ch) {
        series.push({
          label: ch.Name,
          stroke: ch.Color || '#3b82f6',
          width: 2,
          points: { show: false },
          spanGaps: false // draws gaps for sentinel nulls
        });
        data.push([]);
      }
    });

    uplotOptions = {
      title: '',
      id: 'telemetry-plot',
      class: 'my-plot',
      width: 800,
      height: 420,
      cursor: {
        drag: { x: true, y: true, uni: true }
      },
      scales: {
        x: { time: false }
      },
      axes: [
        {
          grid: { stroke: 'rgba(255, 255, 255, 0.03)', width: 1 },
          stroke: '#64748b',
          font: '10px JetBrains Mono'
        },
        {
          grid: { stroke: 'rgba(255, 255, 255, 0.03)', width: 1 },
          stroke: '#64748b',
          font: '10px JetBrains Mono'
        }
      ],
      series: series
    };

    if ($plotterState === 'STOPPED') {
      uplotData = data;
      buffer = data.map(() => []);
    } else {
      const newBuffer = [buffer[0] || []];
      $selectedChannels.forEach((idx, sIdx) => {
        newBuffer.push(buffer[sIdx + 1] || []);
      });
      buffer = newBuffer;
      uplotData = newBuffer;
    }
  }

  function handleFrame(e) {
    if ($plotterState !== 'RUNNING') return;

    const frame = e.detail;
    const tsSec = frame.ts_us / 1000000;

    buffer[0].push(tsSec);

    $selectedChannels.forEach((chIdx, sIdx) => {
      const val = frame.values[chIdx];
      const isDummy = Math.abs(val - DUMMY_VALUE) < 0.01;
      buffer[sIdx + 1].push(isDummy ? null : val);
    });

    const limit = $timeWindow;
    while (buffer[0].length > 0 && (tsSec - buffer[0][0]) > limit) {
      for (let i = 0; i < buffer.length; i++) {
        buffer[i].shift();
      }
    }

    uplotData = [...buffer];
  }

  function startPlot() {
    if ($plotterState === 'STOPPED') {
      buffer = [[]];
      $selectedChannels.forEach(() => buffer.push([]));
      uplotData = [...buffer];
    }
    plotterState.set('RUNNING');
  }

  function pausePlot() {
    plotterState.set('PAUSED');
  }

  function stopPlot() {
    plotterState.set('STOPPED');
    buffer = [[]];
    $selectedChannels.forEach(() => buffer.push([]));
    uplotData = [...buffer];
  }

  function handleTimeWindowChange(secs) {
    timeWindow.set(secs);
    buffer = [[]];
    $selectedChannels.forEach(() => buffer.push([]));
    uplotData = [...buffer];
  }

  function triggerExport() {
    const headers = ['Zeit (s)'];
    $selectedChannels.forEach(idx => {
      headers.push(channels[idx].Name);
    });
    const d = new Date();
    const dateStr = d.getFullYear() + '-' +
      String(d.getMonth()+1).padStart(2,'0') + '-' +
      String(d.getDate()).padStart(2,'0') + '_' +
      String(d.getHours()).padStart(2,'0') + '-' +
      String(d.getMinutes()).padStart(2,'0') + '-' +
      String(d.getSeconds()).padStart(2,'0');
    
    exportToCSV(`plot_export_${dateStr}.csv`, headers, uplotData);
  }

  onMount(() => {
    window.addEventListener('telemetry-frame', handleFrame);
    return () => {
      window.removeEventListener('telemetry-frame', handleFrame);
      unsubMap();
    };
  });
</script>

<div class="flex-1 flex p-6 gap-6 h-[calc(100vh-140px)] overflow-hidden">
  <!-- Channel Selector Sidebar -->
  <div class="w-64 flex-shrink-0 flex flex-col h-full">
    <ChannelSelector
      channels={channels}
      bind:selected={$selectedChannels}
    />
  </div>

  <!-- Main Plotter Container -->
  <div class="flex-1 flex flex-col h-full bg-slate-950/20 border border-slate-900 rounded-2xl p-6 overflow-hidden">
    <!-- Graph Canvas Container -->
    <div class="flex-1 min-h-0 bg-slate-950/40 border border-slate-900 rounded-xl p-4 flex items-center justify-center relative">
      {#if $selectedChannels.length === 0}
        <div class="text-slate-500 flex flex-col items-center gap-2">
          <ZoomIn class="w-8 h-8 text-slate-600 animate-pulse" />
          <p class="text-xs font-semibold uppercase tracking-wider font-display">Keine Kanäle ausgewählt</p>
          <p class="text-[11px] text-slate-600">Bitte wählen Sie in der linken Seitenleiste Kanäle zum Plotten aus.</p>
        </div>
      {:else}
        <uPlotWrapper data={uplotData} options={uplotOptions} />
      {/if}
    </div>

    <!-- Controls Bar -->
    <div class="flex flex-col md:flex-row gap-4 items-center justify-between mt-4 bg-slate-900/30 p-4 border border-slate-900 rounded-xl">
      <!-- Playback buttons -->
      <div class="flex items-center gap-2">
        {#if $plotterState !== 'RUNNING'}
          <button
            on:click={startPlot}
            disabled={$selectedChannels.length === 0}
            class="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-xl px-4 py-2 text-xs font-semibold cursor-pointer select-none active:scale-95 transition-all duration-150 shadow-md shadow-blue-500/10"
          >
            <Play class="w-3.5 h-3.5 fill-current" />
            <span>{$plotterState === 'PAUSED' ? 'Fortsetzen' : 'Start'}</span>
          </button>
        {:else}
          <button
            on:click={pausePlot}
            class="flex items-center gap-2 bg-amber-600 hover:bg-amber-500 text-white rounded-xl px-4 py-2 text-xs font-semibold cursor-pointer select-none active:scale-95 transition-all duration-150 shadow-md shadow-amber-500/10"
          >
            <Pause class="w-3.5 h-3.5 fill-current" />
            <span>Pause</span>
          </button>
        {/if}

        <button
          on:click={stopPlot}
          disabled={$plotterState === 'STOPPED'}
          class="flex items-center gap-2 bg-slate-950 hover:bg-slate-900 border border-slate-800 disabled:opacity-50 text-slate-300 rounded-xl px-4 py-2 text-xs font-semibold cursor-pointer select-none active:scale-95 transition-all duration-150"
        >
          <Square class="w-3.5 h-3.5 fill-current" />
          <span>Stop</span>
        </button>

        <button
          on:click={triggerExport}
          disabled={uplotData[0].length === 0}
          class="flex items-center gap-2 bg-slate-950 hover:bg-slate-900 border border-slate-800 disabled:opacity-50 text-slate-300 rounded-xl px-4 py-2 text-xs font-semibold cursor-pointer select-none active:scale-95 transition-all duration-150 ml-4"
        >
          <Download class="w-3.5 h-3.5" />
          <span>CSV Export</span>
        </button>
      </div>

      <!-- Time Window slider -->
      <div class="flex items-center gap-3">
        <span class="text-xs text-slate-500 font-mono uppercase tracking-wider">Zeitfenster:</span>
        <div class="flex bg-slate-950 border border-slate-850 p-1 rounded-xl">
          {#each timeWindows as sec}
            <button
              on:click={() => handleTimeWindowChange(sec)}
              class="px-2.5 py-1 rounded-lg text-xs font-semibold font-mono transition-all cursor-pointer"
              class:bg-blue-600={sec === $timeWindow}
              class:text-white={sec === $timeWindow}
              class:text-slate-400={sec !== $timeWindow}
              class:hover:text-slate-200={sec !== $timeWindow}
            >
              {sec}s
            </button>
          {/each}
        </div>
      </div>
    </div>

    <!-- Help Notice -->
    {#if $selectedChannels.length > 0}
      <div class="flex items-center gap-2 text-[10px] text-slate-500 mt-2 pl-2">
        <Info class="w-3 h-3 text-slate-600" />
        <span>Tipp: Ziehen Sie auf dem Graphen um zu zoomen. Halten Sie Shift + Ziehen zum Schwenken. Doppelklick setzt die Ansicht zurück.</span>
      </div>
    {/if}
  </div>
</div>
