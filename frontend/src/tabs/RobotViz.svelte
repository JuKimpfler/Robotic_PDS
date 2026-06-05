<script>
  import { Cpu } from 'lucide-svelte';
</script>

<div class="flex-1 flex flex-col items-center justify-center text-slate-500 gap-4 p-8 h-[calc(100vh-140px)]">
  <div class="w-16 h-16 rounded-2xl bg-slate-900 border border-slate-850 flex items-center justify-center text-blue-500 shadow-xl shadow-blue-500/5 animate-pulse">
    <Cpu class="w-8 h-8" />
  </div>
  <h2 class="text-lg font-bold font-display text-slate-300">Grafische Visualisierung</h2>
  <p class="text-sm max-w-md text-center text-slate-500">
    Diese Ansicht befindet sich in der Entwicklung. Zukünftige Updates werden 2D-Robotermodelle (basierend auf <code>robot_viz.json</code>) mit Datenüberlagerungen und Farbverläufen einbinden.
  </p>
  <div class="flex gap-2">
    <span class="text-[10px] bg-slate-900 text-slate-600 px-3 py-1 rounded-full font-mono">
      Spec: robot_viz.json
    </span>
    <span class="text-[10px] bg-slate-900 text-slate-600 px-3 py-1 rounded-full font-mono">
      Engine: Inline SVG DOM
    </span>
  </div>
</div>
