<script lang="ts">
  import { page } from "$app/state";

  import { t } from "#lib/i18n.svelte.ts";
</script>

<!-- Replaces SvelteKit's own error page, which is in English only. -->
<p role="alert">{t(page.status === 404 ? "error.not_found" : "error.network")}</p>
