<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";

  import { api } from "#lib/api.ts";
  import { errorKey } from "#lib/errors.ts";
  import { t, type MessageKey } from "#lib/i18n.svelte.ts";

  import type { PageProps } from "./$types";

  let { data }: PageProps = $props();
  let error: MessageKey | null = $state(null);

  async function signOut() {
    error = null;
    try {
      const { response, error: body } = await api.POST("/v1/auth/signout");
      if (!response.ok) {
        error = errorKey(body);
        return;
      }
    } catch {
      error = errorKey(undefined);
      return;
    }
    await goto(resolve("/signin"));
  }
</script>

<p>{t("home.signed_in_as", { name: data.user.name })}</p>
<button type="button" onclick={signOut}>{t("auth.sign_out")}</button>
{#if error}<p role="alert">{t(error)}</p>{/if}
