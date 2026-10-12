<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { onMount } from "svelte";

  import { api } from "#lib/api.ts";
  import { apiState, type ApiState } from "#lib/health.ts";
  import { t } from "#lib/i18n.svelte.ts";

  import type { PageProps } from "./$types";

  let { data }: PageProps = $props();
  let health: ApiState = $state({ kind: "checking" });

  onMount(async () => {
    try {
      health = apiState((await api.GET("/v1/health")).data);
    } catch {
      health = { kind: "down" };
    }
  });

  async function signOut() {
    await api.POST("/v1/auth/signout");
    await goto(resolve("/signin"));
  }
</script>

<p>{t("home.signed_in_as", { name: data.user.name })}</p>
<button type="button" onclick={signOut}>{t("auth.sign_out")}</button>

{#if health.kind === "checking"}
  <p>{t("health.checking")}</p>
{:else if health.kind === "up"}
  <p>{t("health.up", { version: health.version })}</p>
{:else}
  <p>{t("health.down")}</p>
{/if}
