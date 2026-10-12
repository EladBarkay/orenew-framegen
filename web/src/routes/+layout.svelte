<script lang="ts">
  import type { Snippet } from "svelte";

  import { parts, t } from "#lib/i18n.svelte.ts";
  import { SOURCE_URL } from "#lib/project.ts";

  let { children }: { children: Snippet } = $props();
</script>

<svelte:head>
  <title>{t("app.name")}</title>
</svelte:head>

<main>
  <h1>{t("app.name")}</h1>
  {@render children()}
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
