<script>
  import { onMount } from 'svelte';
  import { paramDefinitions, dirtyParams, presets } from '../stores/params.js';
  import { wsConnected } from '../stores/connection.js';
  import { Save, Send, RefreshCw, Sliders, Check, AlertCircle } from 'lucide-svelte';

  let params = [];
  let dirty = {};
  let selectedGroup = 'Alle';
  let isSending = false;
  let isSaving = false;
  let statusMsg = '';
  let statusError = false;

  const unsubParams = paramDefinitions.subscribe(val => { params = val; });
  const unsubDirty = dirtyParams.subscribe(val => { dirty = val; });

  $: groups = ['Alle', ...new Set(params.map(p => p.group).filter(Boolean))];

  $: filteredParams = params.filter(p => {
    if (selectedGroup === 'Alle') return true;
    return p.group === selectedGroup;
  });

  async function loadParams() {
    try {
      const res = await fetch('/api/params');
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      paramDefinitions.set(data.params || []);
      dirtyParams.set({}); // clear edits
    } catch (e) {
      console.error('Error loading parameters:', e);
      showStatus('Fehler beim Laden der Parameter: ' + e.message, true);
    }
  }

  function handleEdit(index, type, valStr) {
    let val = parseFloat(valStr);
    if (isNaN(val)) return;

    // Type validation constraints
    const original = params.find(p => p.index === index);
    if (!original) return;

    if (val < original.min) val = original.min;
    if (val > original.max) val = original.max;

    if (type === 'int32') {
      val = Math.round(val);
    } else if (type === 'bool') {
      val = val > 0 ? 1 : 0;
    }

    dirtyParams.update(d => {
      if (val === original.default) {
        delete d[index];
      } else {
        d[index] = val;
      }
      return { ...d };
    });
  }

  async function sendChanged() {
    const keys = Object.keys(dirty);
    if (keys.length === 0) return;

    isSending = true;
    showStatus('Sende Parameter...', false);

    try {
      if (keys.length === 1) {
        // Send single parameter
        const idx = parseInt(keys[0]);
        const val = dirty[idx];
        const res = await fetch(`/api/params/${idx}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: val })
        });
        if (!res.ok) throw new Error(await res.text());
      } else {
        // Send batch
        const batch = keys.map(k => ({ index: parseInt(k), value: dirty[k] }));
        const res = await fetch('/api/params/batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(batch)
        });
        if (!res.ok) throw new Error(await res.text());
      }

      showStatus('Parameter erfolgreich gesendet!', false);
      await loadParams(); // reload parameters
    } catch (e) {
      showStatus('Senden fehlgeschlagen: ' + e.message, true);
    } finally {
      isSending = false;
    }
  }

  async function saveToEEPROM() {
    isSaving = true;
    showStatus('Speichere auf Teensy EEPROM...', false);
    try {
      const res = await fetch('/api/params/save', { method: 'POST' });
      if (!res.ok) throw new Error(await res.text());
      showStatus('Einstellungen im EEPROM gespeichert!', false);
    } catch (e) {
      showStatus('Speichern fehlgeschlagen: ' + e.message, true);
    } finally {
      isSaving = false;
    }
  }

  function resetEdits() {
    dirtyParams.set({});
  }

  function showStatus(msg, isErr = false) {
    statusMsg = msg;
    statusError = isErr;
    setTimeout(() => {
      if (statusMsg === msg) {
        statusMsg = '';
      }
    }, 4000);
  }

  onMount(() => {
    loadParams();
    return () => {
      unsubParams();
      unsubDirty();
    };
  });
</script>

<div class="flex-1 flex flex-col p-6 overflow-hidden h-[calc(100vh-140px)]">
  <!-- Toolbar -->
  <div class="flex flex-col md:flex-row gap-4 items-center justify-between mb-4 bg-slate-900/30 p-4 border border-slate-900 rounded-2xl">
    <div class="flex flex-wrap gap-4 items-center w-full md:w-auto">
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

      <button
        on:click={loadParams}
        class="flex items-center gap-1.5 bg-slate-950 hover:bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200 rounded-xl px-3 py-1.5 text-xs font-semibold cursor-pointer transition-colors"
      >
        <RefreshCw class="w-3.5 h-3.5" />
        <span>Neu laden</span>
      </button>
    </div>

    <!-- Actions -->
    <div class="flex items-center gap-3 w-full md:w-auto justify-between md:justify-end">
      <!-- Info label -->
      {#if Object.keys(dirty).length > 0}
        <span class="text-xs text-amber-400 font-mono flex items-center gap-1">
          <AlertCircle class="w-3.5 h-3.5" />
          <span>{Object.keys(dirty).length} Geändert</span>
        </span>
      {/if}

      <!-- Reset edits -->
      <button
        on:click={resetEdits}
        disabled={Object.keys(dirty).length === 0}
        class="bg-slate-950 hover:bg-slate-900 disabled:opacity-30 border border-slate-800 text-slate-400 hover:text-slate-200 rounded-xl px-3.5 py-1.5 text-xs font-semibold cursor-pointer transition-colors"
      >
        Verwerfen
      </button>

      <!-- Send edits -->
      <button
        on:click={sendChanged}
        disabled={Object.keys(dirty).length === 0 || isSending}
        class="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded-xl px-4 py-1.5 text-xs font-semibold cursor-pointer transition-colors shadow-md shadow-blue-500/10"
      >
        <Send class="w-3.5 h-3.5" />
        <span>Senden</span>
      </button>

      <!-- Save EEPROM -->
      <button
        on:click={saveToEEPROM}
        disabled={isSaving || !$wsConnected}
        class="flex items-center gap-1.5 bg-slate-950 hover:bg-slate-900 border border-slate-800 disabled:opacity-40 text-emerald-400 hover:text-emerald-300 rounded-xl px-4 py-1.5 text-xs font-semibold cursor-pointer transition-colors"
      >
        <Save class="w-3.5 h-3.5" />
        <span>EEPROM Speichern</span>
      </button>
    </div>
  </div>

  <!-- Status alert overlay -->
  {#if statusMsg}
    <div
      class="mb-4 px-4 py-2.5 rounded-xl border flex items-center gap-2 text-xs font-mono transition-all duration-300"
      class:bg-rose-950={statusError}
      class:bg-slate-900={!statusError}
      class:border-rose-900={statusError}
      class:border-slate-800={!statusError}
      class:text-rose-400={statusError}
      class:text-slate-300={!statusError}
    >
      <Sliders class="w-4 h-4 text-blue-400" />
      <span>{statusMsg}</span>
    </div>
  {/if}

  <!-- Header -->
  <div class="w-full bg-slate-950 border border-slate-900 rounded-t-xl grid grid-cols-12 text-xs text-slate-500 font-mono font-semibold py-3 px-6 select-none border-b">
    <div class="col-span-1">IDX</div>
    <div class="col-span-3">NAME</div>
    <div class="col-span-1">TYP</div>
    <div class="col-span-2">WERT</div>
    <div class="col-span-1">EINHEIT</div>
    <div class="col-span-1">MIN</div>
    <div class="col-span-1">MAX</div>
    <div class="col-span-2">BESCHREIBUNG</div>
  </div>

  <!-- Parameter Table body -->
  <div class="flex-1 bg-slate-950/20 border border-slate-900 border-t-0 rounded-b-xl overflow-y-auto">
    {#if filteredParams.length === 0}
      <div class="w-full h-full flex flex-col items-center justify-center text-slate-500 gap-2 p-8">
        <span class="text-xl">⚙️</span>
        <p class="text-sm">Keine konfigurierbaren Parameter geladen.</p>
      </div>
    {:else}
      <div class="w-full">
        {#each filteredParams as p (p.index)}
          {@const isDirty = dirty[p.index] !== undefined}
          {@const currentVal = isDirty ? dirty[p.index] : p.value}
          <div
            class="grid grid-cols-12 py-2 px-6 border-b border-slate-900/50 hover:bg-slate-900/20 text-xs font-mono items-center transition-colors"
            class:bg-amber-950={isDirty}
          >
            <!-- Index -->
            <div class="col-span-1 text-slate-600 font-semibold">{p.index}</div>

            <!-- Name -->
            <div class="col-span-3 text-slate-200 font-sans font-medium">{p.name}</div>

            <!-- Type -->
            <div class="col-span-1 text-slate-500 text-[10px]">{p.type}</div>

            <!-- Value input -->
            <div class="col-span-2 pr-4 flex items-center gap-1.5">
              <input
                type="number"
                step="any"
                value={currentVal}
                on:change={(e) => handleEdit(p.index, p.type, e.target.value)}
                class="w-full bg-slate-950 border rounded-lg px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-blue-500/50"
                class:border-amber-700={isDirty}
                class:border-slate-800={!isDirty}
                class:text-amber-400={isDirty}
              />
              {#if isDirty}
                <span class="text-[9px] bg-amber-950 text-amber-400 border border-amber-900/50 px-1 rounded flex items-center gap-0.5" title="Änderung noch nicht gesendet">
                  DIRTY
                </span>
              {/if}
            </div>

            <!-- Unit -->
            <div class="col-span-1 text-slate-400">{p.unit || '—'}</div>

            <!-- Min -->
            <div class="col-span-1 text-slate-500">{p.min}</div>

            <!-- Max -->
            <div class="col-span-1 text-slate-500">{p.max}</div>

            <!-- Description -->
            <div class="col-span-2 text-slate-500 text-[10px] truncate font-sans" title={p.description}>
              {p.description || '—'}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>
