<script>
  import { onMount } from 'svelte';

  export let items = [];
  export let itemHeight = 42; // standard row height in px

  let container;
  let scrollTop = 0;
  let containerHeight = 500;

  // Reactive calculations for virtualized indices
  $: totalHeight = items.length * itemHeight;
  $: startIndex = Math.max(0, Math.floor(scrollTop / itemHeight) - 5); // padding of 5 rows
  $: endIndex = Math.min(items.length, Math.ceil((scrollTop + containerHeight) / itemHeight) + 5);
  $: visibleItems = items.slice(startIndex, endIndex);
  $: offsetY = startIndex * itemHeight;

  function handleScroll(e) {
    scrollTop = e.target.scrollTop;
  }

  function handleResize() {
    if (container) {
      containerHeight = container.clientHeight || 500;
    }
  }

  onMount(() => {
    handleResize();
    // Use ResizeObserver for more robust height tracking
    const ro = new ResizeObserver(handleResize);
    if (container) ro.observe(container);

    return () => {
      ro.disconnect();
    };
  });
</script>

<div
  bind:this={container}
  on:scroll={handleScroll}
  class="w-full h-full overflow-y-auto relative border border-slate-900 rounded-xl bg-slate-950/20"
>
  <div style="height: {totalHeight}px; width: 100%; position: relative;" class="w-full">
    <div
      style="transform: translateY({offsetY}px); position: absolute; left: 0; right: 0; top: 0;"
      class="w-full"
    >
      <slot visibleItems={visibleItems} startIndex={startIndex}></slot>
    </div>
  </div>
</div>
