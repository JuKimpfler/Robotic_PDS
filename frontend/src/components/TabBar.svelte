<script>
  import { Database, LineChart, Cpu, Sliders } from 'lucide-svelte';
  
  // Two-way bound active tab state
  export let activeTab = 'data';
</script>

<div class="w-full bg-slate-900/40 backdrop-blur-sm border-b border-slate-900 flex px-4">
  <button
    on:click={() => activeTab = 'data'}
    class="flex items-center gap-2 px-5 py-3 border-b-2 font-medium text-xs md:text-sm tracking-wide transition-all duration-300 cursor-pointer"
    class:border-blue-500={activeTab === 'data'}
    class:text-blue-400={activeTab === 'data'}
    class:border-transparent={activeTab !== 'data'}
    class:text-slate-400={activeTab !== 'data'}
    class:hover:text-slate-200={activeTab !== 'data'}
  >
    <Database class="w-4 h-4" />
    <span>Daten</span>
  </button>

  <button
    on:click={() => activeTab = 'plotter'}
    class="flex items-center gap-2 px-5 py-3 border-b-2 font-medium text-xs md:text-sm tracking-wide transition-all duration-300 cursor-pointer"
    class:border-blue-500={activeTab === 'plotter'}
    class:text-blue-400={activeTab === 'plotter'}
    class:border-transparent={activeTab !== 'plotter'}
    class:text-slate-400={activeTab !== 'plotter'}
    class:hover:text-slate-200={activeTab !== 'plotter'}
  >
    <LineChart class="w-4 h-4" />
    <span>Plotter</span>
  </button>

  <button
    on:click={() => activeTab = 'robot'}
    class="flex items-center gap-2 px-5 py-3 border-b-2 font-medium text-xs md:text-sm tracking-wide transition-all duration-300 cursor-pointer"
    class:border-blue-500={activeTab === 'robot'}
    class:text-blue-400={activeTab === 'robot'}
    class:border-transparent={activeTab !== 'robot'}
    class:text-slate-400={activeTab !== 'robot'}
    class:hover:text-slate-200={activeTab !== 'robot'}
  >
    <Cpu class="w-4 h-4" />
    <span>Visualisierung</span>
  </button>

  <button
    on:click={() => activeTab = 'params'}
    class="flex items-center gap-2 px-5 py-3 border-b-2 font-medium text-xs md:text-sm tracking-wide transition-all duration-300 cursor-pointer"
    class:border-blue-500={activeTab === 'params'}
    class:text-blue-400={activeTab === 'params'}
    class:border-transparent={activeTab !== 'params'}
    class:text-slate-400={activeTab !== 'params'}
    class:hover:text-slate-200={activeTab !== 'params'}
  >
    <Sliders class="w-4 h-4" />
    <span>Parameter</span>
  </button>
</div>
