<script>
  import { onMount } from 'svelte';
  import { channelMap, liveValues, minValues, maxValues, resetMinMax } from '../stores/channelData.js';
  import { wsConnected } from '../stores/connection.js';
  import VirtualTable from '../components/VirtualTable.svelte';
  import { formatValue } from '../lib/formatters.js';
  import { DUMMY_VALUE } from '../lib/constants.js';
  import { Search, RefreshCw, ChevronUp, ChevronDown } from 'lucide-svelte';

  let channels = [];
  let currentValues = new Float32Array(0);
  let currentMins = new Float32Array(0);
  let currentMaxes = new Float32Array(0);

  // Subscriptions
  const unsubMap = channelMap.subscribe(val => { channels = val; });
  const unsubVal = liveValues.subscribe(val => { currentValues = val; });
  const unsubMin = minValues.subscribe(val => { currentMins = val; });
  const unsubMax = maxValues.subscribe(val => { currentMaxes = val; });

  let displayedItems = [];
  let filterText = '';
  let selectedGroup = 'Alle';
  let sortBy = 'index'; // 'index' | 'name' | 'value' | 'min' | 'max'
  let sortAsc = true;

  $: groups = ['Alle', ...new Set(channels.map(ch => ch.Group).filter(Boolean))];

  let interval;

  function updateDisplayItems() {
    if (channels.length === 0) {
      displayedItems = [];
      return;
    }

    const items = [];
    for (let i = 0; i < channels.length; i++) {
      const ch = channels[i];
      const val = currentValues[i] !== undefined ? currentValues[i] : DUMMY_VALUE;
      const min = currentMins[i] !== undefined ? currentMins[i] : Infinity;
      const max = currentMaxes[i] !== undefined ? currentMaxes[i] : -Infinity;

      // Sentinel active rule: hide inactive channels sending DUMMY_VALUE (9898.0)
      if (Math.abs(val - DUMMY_VALUE) < 0.01) {
        continue;
      }

      if (selectedGroup !== 'Alle' && ch.Group !== selectedGroup) {
        continue;
      }

      if (filterText && !ch.Name.toLowerCase().includes(filterText.toLowerCase())) {
        continue;
      }

      items.push({
        index: ch.Index,
        name: ch.Name,
        group: ch.Group,
        unit: ch.Unit,
        precision: ch.Precision,
        color: ch.Color,
        val: val,
        min: min,
        max: max
      });
    }

    // Sort items array
    items.sort((a, b) => {
      let fieldA, fieldB;
      switch (sortBy) {
        case 'index':
          fieldA = a.index;
          fieldB = b.index;
          break;
        case 'name':
          fieldA = a.name;
          fieldB = b.name;
          break;
        case 'value':
          fieldA = a.val;
          fieldB = b.val;
          break;
        case 'min':
          fieldA = a.min;
          fieldB = b.min;
          break;
        case 'max':
          fieldA = a.max;
          fieldB = b.max;
          break;
        default:
          fieldA = a.index;
          fieldB = b.index;
      }

      if (fieldA < fieldB) return sortAsc ? -1 : 1;
      if (fieldA > fieldB) return sortAsc ? 1 : -1;
      return 0;
    });

    displayedItems = items;
  }

  function toggleSort(col) {
    if (sortBy === col) {
      sortAsc = !sortAsc;
    } else {
      sortBy = col;
      sortAsc = true;
    }
  }

  onMount(() => {
    // Decoupled 30 Hz rendering loop to prevent high frame-rate lockups
    interval = setInterval(updateDisplayItems, 33);
    return () => {
      clearInterval(interval);
      unsubMap();
      unsubVal();
      unsubMin();
      unsubMax();
    };
  });
</script>

<div class="flex-1 flex flex-col p-6 overflow-hidden h-[calc(100vh-140px)]">
  <!-- Toolbar -->
  <div class="flex flex-col md:flex-row gap-4 items-center justify-between mb-4 bg-slate-900/30 p-4 border border-slate-900 rounded-2xl">
    <div class="flex flex-wrap gap-4 items-center w-full md:w-auto">
      <!-- Search Input -->
      <div class="relative w-full md:w-64">
        <Search class="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          bind:value={filterText}
          placeholder="Kanäle filtern..."
          class="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-1.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500/50"
        />
      </div>

      <!-- Group Select -->
      <div class="flex items-center gap-2">
        <span class="text-xs text-slate-500 uppercase tracking-wider font-mono">Gruppe:</span>
        <select
          bind:value={selectedGroup}
          class="bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500/50 cursor-pointer"
        >
          {#each groups as gp}
            <option value={gp}>{gp}</option>
          {/each}
        </select>
      </div>
    </div>

    <!-- Active Counters & Reset -->
    <div class="flex items-center gap-4 w-full md:w-auto justify-between md:justify-end">
      <span class="text-xs text-slate-400 font-mono">
        Aktiv: <strong class="text-emerald-400">{displayedItems.length}</strong> / {channels.length} Kanäle
      </span>

      <button
        on:click={resetMinMax}
        class="flex items-center gap-2 bg-slate-950 hover:bg-slate-900 border border-slate-800 rounded-xl px-4 py-1.5 text-xs font-semibold text-slate-300 cursor-pointer transition-colors active:scale-95 duration-150"
      >
        <RefreshCw class="w-3.5 h-3.5" />
        <span>Min/Max Reset</span>
      </button>
    </div>
  </div>

  <!-- Table Header -->
  <div class="w-full bg-slate-950 border border-slate-900 rounded-t-xl grid grid-cols-6 text-xs text-slate-500 font-mono font-semibold py-3 px-6 select-none border-b">
    <button on:click={() => toggleSort('name')} class="flex items-center gap-1 hover:text-slate-200 text-left cursor-pointer">
      NAME
      {#if sortBy === 'name'}
        {#if sortAsc}<ChevronUp class="w-3 h-3" />{:else}<ChevronDown class="w-3 h-3" />{/if}
      {/if}
    </button>
    <button on:click={() => toggleSort('group')} class="flex items-center gap-1 hover:text-slate-200 text-left cursor-pointer">
      GRUPPE
      {#if sortBy === 'group'}
        {#if sortAsc}<ChevronUp class="w-3 h-3" />{:else}<ChevronDown class="w-3 h-3" />{/if}
      {/if}
    </button>
    <button on:click={() => toggleSort('value')} class="flex items-center gap-1 hover:text-slate-200 text-left cursor-pointer">
      WERT
      {#if sortBy === 'value'}
        {#if sortAsc}<ChevronUp class="w-3 h-3" />{:else}<ChevronDown class="w-3 h-3" />{/if}
      {/if}
    </button>
    <div class="text-left">EINHEIT</div>
    <button on:click={() => toggleSort('min')} class="flex items-center gap-1 hover:text-slate-200 text-left cursor-pointer">
      MIN
      {#if sortBy === 'min'}
        {#if sortAsc}<ChevronUp class="w-3 h-3" />{:else}<ChevronDown class="w-3 h-3" />{/if}
      {/if}
    </button>
    <button on:click={() => toggleSort('max')} class="flex items-center gap-1 hover:text-slate-200 text-left cursor-pointer">
      MAX
      {#if sortBy === 'max'}
        {#if sortAsc}<ChevronUp class="w-3 h-3" />{:else}<ChevronDown class="w-3 h-3" />{/if}
      {/if}
    </button>
  </div>

  <!-- Table Body (Virtualized) -->
  <div class="flex-1 min-h-0 bg-slate-950/20 border border-slate-900 border-t-0 rounded-b-xl overflow-hidden">
    {#if displayedItems.length === 0}
      <div class="w-full h-full flex flex-col items-center justify-center text-slate-500 gap-2 p-8">
        <span class="text-2xl">📭</span>
        <p class="text-sm">Keine aktiven Telemetriedaten vorhanden.</p>
        <p class="text-xs text-slate-600">Bitte WebSocket-Verbindung oder Hardware-Stream prüfen.</p>
      </div>
    {:else}
      <VirtualTable items={displayedItems} itemHeight={42} let:visibleItems>
        {#each visibleItems as item (item.index)}
          <div class="grid grid-cols-6 py-2.5 px-6 border-b border-slate-900/50 hover:bg-slate-900/20 text-sm font-mono items-center transition-colors">
            <!-- Name -->
            <div class="flex items-center gap-2 truncate font-sans font-medium text-slate-200">
              {#if item.color}
                <span class="w-2 h-2 rounded-full flex-shrink-0" style="background-color: {item.color}; box-shadow: 0 0 4px {item.color};"></span>
              {/if}
              <span class="truncate">{item.name}</span>
            </div>

            <!-- Group -->
            <div class="text-slate-500 text-xs truncate font-sans">{item.group}</div>

            <!-- Value -->
            <div class="font-semibold text-slate-100">
              {$wsConnected ? formatValue(item.val, item.precision) : '—'}
            </div>

            <!-- Unit -->
            <div class="text-slate-400 text-xs font-sans">{item.unit || '—'}</div>

            <!-- Min -->
            <div class="text-blue-300/80 font-medium">
              {formatValue(item.min, item.precision)}
            </div>

            <!-- Max -->
            <div class="text-rose-300/80 font-medium">
              {formatValue(item.max, item.precision)}
            </div>
          </div>
        {/each}
      </VirtualTable>
    {/if}
  </div>
</div>
