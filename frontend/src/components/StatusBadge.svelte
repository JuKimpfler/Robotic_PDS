<script>
  export let status = 'off'; // 'on' | 'off' | 'transitioning' | boolean
</script>

<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-900 border border-slate-800 text-slate-300">
  <span
    class="w-2 h-2 rounded-full transition-all duration-500"
    class:bg-emerald-500={status === 'on' || status === true}
    class:bg-amber-500={status === 'transitioning'}
    class:bg-rose-500={status === 'off' || status === false}
    class:pulse-glow={status === 'on' || status === 'transitioning' || status === true}
    style="color: currentColor;"
  ></span>
  <slot></slot>
</span>
