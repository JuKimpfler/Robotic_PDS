<script>
  import { onMount } from 'svelte';
  import { connect } from './ws/client.js';
  import Header from './components/Header.svelte';
  import TabBar from './components/TabBar.svelte';
  import DataTable from './tabs/DataTable.svelte';
  import Plotter from './tabs/Plotter.svelte';
  import RobotViz from './tabs/RobotViz.svelte';
  import Parameters from './tabs/Parameters.svelte';

  let activeTab = 'data';

  onMount(() => {
    connect();
  });
</script>

<div class="min-h-screen flex flex-col bg-[#070b13] text-slate-100 selection:bg-blue-500/20 selection:text-blue-300">
  <!-- Top header with status information -->
  <Header />

  <!-- Navigation bar between views -->
  <TabBar bind:activeTab={activeTab} />

  <!-- Tab views -->
  <main class="flex-1 flex flex-col min-h-0 bg-slate-950/5">
    {#if activeTab === 'data'}
      <DataTable />
    {:else if activeTab === 'plotter'}
      <Plotter />
    {:else if activeTab === 'robot'}
      <RobotViz />
    {:else if activeTab === 'params'}
      <Parameters />
    {/if}
  </main>
</div>
