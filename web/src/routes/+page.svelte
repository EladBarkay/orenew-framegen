<script lang="ts">
  import { createFrameGenClient } from "@framegen/sdk";
  import { onMount } from "svelte";

  import { apiState, type ApiState } from "#lib/health.ts";

  // Placeholder home page for T-02: proves the web app reaches the API through the SDK.
  // Text moves to locale files in T-09.
  let state: ApiState = $state({ kind: "checking" });

  onMount(async () => {
    const client = createFrameGenClient({ baseUrl: window.location.origin });
    try {
      const { data } = await client.GET("/v1/health");
      state = apiState(data);
    } catch {
      state = { kind: "down" };
    }
  });
</script>

<svelte:head>
  <title>FrameGen</title>
</svelte:head>

<main>
  <h1>FrameGen</h1>
  {#if state.kind === "checking"}
    <p>Checking the API…</p>
  {:else if state.kind === "up"}
    <p>API is up (version {state.version}).</p>
  {:else}
    <p>The API cannot be reached.</p>
  {/if}
</main>

<style>
  main {
    font-family: system-ui, sans-serif;
    margin-block: 4rem;
    margin-inline: auto;
    max-inline-size: 40rem;
    padding-inline: 1rem;
  }
</style>
