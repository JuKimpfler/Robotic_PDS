<script>
  import { createEventDispatcher } from 'svelte';
  import { Search, ChevronDown, ChevronRight, CheckSquare, Square } from 'lucide-svelte';

  export let channels = [];
  export let selected = []; // array of selected channel indices

  const dispatch = createEventDispatcher();
  let filterText = '';
  let collapsedGroups = {};

  $: grouped = channels.reduce((acc, ch) => {
    const groupName = ch.group || 'Unclassified';
    if (!acc[groupName]) {
      acc[groupName] = [];
    }
    acc[groupName].push(ch);
    return acc;
  }, {});

  $: filteredGroups = Object.keys(grouped).reduce((acc, gName) => {
    const list = grouped[gName].filter(ch =>
      ch.name.toLowerCase().includes(filterText.toLowerCase())
    );
    if (list.length > 0) {
      acc[gName] = list;
    }
    return acc;
  }, {});

  function toggleChannel(idx) {
    const isSel = selected.includes(idx);
    if (isSel) {
      selected = selected.filter(id => id !== idx);
    } else {
      if (selected.length >= 8) {
        alert("Maximum 8 Kanäle können gleichzeitig geplottet werden.");
        return;
      }
      selected = [...selected, idx];
    }
    dispatch('change', selected);
  }

  function toggleGroup(gName) {
    collapsedGroups[gName] = !collapsedGroups[gName];
  }

  function selectAll() {
    const visibleIdxs = [];
    Object.values(filteredGroups).forEach(list => {
      list.forEach(ch => visibleIdxs.push(ch.index));
    });
    selected = visibleIdxs.slice(0, 8);
    dispatch('change', selected);
  }

  function deselectAll() {
    selected = [];
    dispatch('change', selected);
  }
</script>

<div class="flex flex-col h-full bg-slate-950 border border-slate-900 rounded-2xl overflow-hidden shadow-inner">
  <!-- Search -->
  <div class="p-3 border-b border-slate-900 relative">
    <Search class="w-4 h-4 text-slate-500 absolute left-6 top-1/2 -translate-y-1/2" />
    <input
      type="text"
      bind:value={filterText}
      placeholder="Kanäle filtern..."
      class="w-full bg-slate-900 border border-slate-800 rounded-xl pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500/50 transition-colors"
    />
  </div>

  <!-- Selection Counter -->
  <div class="px-4 py-2 bg-slate-950 border-b border-slate-900 flex justify-between items-center text-[10px] text-slate-400 font-mono">
    <span>Auswahl: <strong class="text-blue-400">{selected.length}/8</strong></span>
    <div class="flex gap-2">
      <button on:click={selectAll} class="hover:text-blue-400 cursor-pointer">Alle (max 8)</button>
      <span>|</span>
      <button on:click={deselectAll} class="hover:text-rose-400 cursor-pointer">Zurücksetzen</button>
    </div>
  </div>

  <!-- Channels List -->
  <div class="flex-1 overflow-y-auto p-2 space-y-1.5 scrollbar-thin">
    {#each Object.keys(filteredGroups) as gName}
      <div class="mb-1">
        <!-- Header -->
        <button
          on:click={() => toggleGroup(gName)}
          class="w-full flex items-center justify-between py-1 px-1.5 hover:bg-slate-900/50 rounded-lg text-left text-xs font-semibold text-slate-300 font-display cursor-pointer transition-colors"
        >
          <span class="flex items-center gap-1">
            {#if collapsedGroups[gName]}
              <ChevronRight class="w-3.5 h-3.5 text-slate-500" />
            {:else}
              <ChevronDown class="w-3.5 h-3.5 text-slate-500" />
            {/if}
            {gName}
          </span>
          <span class="text-[9px] bg-slate-900 text-slate-500 px-1.5 py-0.5 rounded-full font-mono">
            {filteredGroups[gName].length}
          </span>
        </button>

        <!-- Channels -->
        {#if !collapsedGroups[gName]}
          <div class="pl-2 mt-1 space-y-0.5 border-l border-slate-900 ml-2.5">
            {#each filteredGroups[gName] as ch}
              <button
                on:click={() => toggleChannel(ch.index)}
                class="w-full flex items-center gap-2 py-1 px-2 hover:bg-slate-900/30 rounded-lg text-left text-[11px] text-slate-400 transition-colors cursor-pointer"
                class:text-slate-100={selected.includes(ch.index)}
              >
                {#if selected.includes(ch.index)}
                  <CheckSquare class="w-3.5 h-3.5 text-blue-500" />
                {:else}
                  <Square class="w-3.5 h-3.5 text-slate-700" />
                {/if}
                <span class="truncate flex-1">{ch.name}</span>
                {#if ch.color}
                  <span class="w-1.5 h-1.5 rounded-full shadow-lg" style="background-color: {ch.color}; box-shadow: 0 0 4px {ch.color}"></span>
                {/if}
              </button>
            {/each}
          </div>
        {/if}
      </div>
    {/each}
  </div>
</div>
