<script>
  import { onMount, onDestroy } from 'svelte';
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';

  export let data = [];
  export let options = {};

  let container;
  let chart = null;

  function initChart() {
    if (chart) {
      chart.destroy();
      chart = null;
    }
    if (container && options && data) {
      try {
        chart = new uPlot(options, data, container);
      } catch (err) {
        console.error("uPlot initialization failed:", err);
      }
    }
  }

  // Reactively set data on change without rebuilding the chart
  $: if (chart && data) {
    chart.setData(data);
  }

  // Reactively rebuild chart when options change (e.g. series selections)
  $: if (options) {
    initChart();
  }

  onMount(() => {
    initChart();

    const resizeObserver = new ResizeObserver((entries) => {
      if (!chart) return;
      for (let entry of entries) {
        // Adjust padding offset
        const width = Math.floor(entry.contentRect.width);
        const height = Math.floor(entry.contentRect.height);
        if (width > 0 && height > 0) {
          chart.setSize({ width, height });
        }
      }
    });

    if (container) {
      resizeObserver.observe(container);
    }

    return () => {
      resizeObserver.disconnect();
      if (chart) chart.destroy();
    };
  });

  onDestroy(() => {
    if (chart) {
      chart.destroy();
    }
  });
</script>

<div bind:this={container} class="w-full h-full min-h-[200px] overflow-hidden"></div>
