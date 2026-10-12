<script lang="ts">
  import { page } from "$app/state";

  import { t, type MessageKey } from "#lib/i18n.svelte.ts";

  // Replaces SvelteKit's own error page, which is in English only.
  const MESSAGES: Record<number, MessageKey> = {
    404: "error.not_found",
    502: "error.network",
  };
</script>

<p role="alert">{t(MESSAGES[page.status] ?? "error.unavailable")}</p>
