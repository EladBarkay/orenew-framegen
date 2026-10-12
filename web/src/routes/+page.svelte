<script lang="ts">
  import { createFrameGenClient } from "@framegen/sdk";
  import { onMount } from "svelte";

  import { apiState, type ApiState } from "#lib/health.ts";
  import { parts, t } from "#lib/i18n.svelte.ts";
  import { SOURCE_URL } from "#lib/project.ts";

  // Placeholder home page: proves the web app reaches the API through the SDK.
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
  <title>{t("app.name")}</title>
</svelte:head>

<main>
  <h1>{t("app.name")}</h1>
  {#if state.kind === "checking"}
    <p>{t("health.checking")}</p>
  {:else if state.kind === "up"}
    <p>{t("health.up", { version: state.version })}</p>
  {:else}
    <p>{t("health.down")}</p>
  {/if}
</main>

<footer>
  {#each parts("footer.licence") as part, index (index)}
    {#if "text" in part}{part.text}{:else if part.slot === "licence"}<a
        href="https://www.gnu.org/licenses/agpl-3.0.html">{t("footer.licence_name")}</a
      >{/if}
  {/each}
  <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- external link -->
  <a href={SOURCE_URL}>{t("footer.source")}</a>
</footer>

<style>
  main,
  footer {
    font-family: system-ui, sans-serif;
    margin-block: 4rem;
    margin-inline: auto;
    max-inline-size: 40rem;
    padding-inline: 1rem;
  }

  footer {
    color: #555;
    font-size: 0.875rem;
    margin-block: 2rem;
  }
</style>
