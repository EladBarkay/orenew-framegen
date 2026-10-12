<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";

  import { api } from "#lib/api.ts";
  import { errorKey } from "#lib/errors.ts";
  import { t, type MessageKey } from "#lib/i18n.svelte.ts";
  import {
    choose,
    createStudio,
    forget,
    preferredFor,
    same,
    select,
    workspace,
    type Workspace,
  } from "#lib/workspace.svelte.ts";

  import type { PageProps } from "./$types";

  let { data }: PageProps = $props();
  let error: MessageKey | null = $state(null);
  // The page's list, plus studios created here since it was loaded.
  let added: Workspace[] = $state([]);
  const workspaces = $derived([
    ...data.workspaces,
    ...added.filter((a) => !data.workspaces.some((w) => w.id === a.id)),
  ]);
  let studioName = $state("");

  const ROLES = { owner: "role.owner", admin: "role.admin", member: "role.member" } as const;

  $effect.pre(() => {
    const chosen = choose(workspaces, preferredFor(data.user.id));
    // Also when only the details changed (a new role or name). Compared by value: state
    // holds its own proxy of the object, never the object itself.
    if (chosen && !same(chosen, workspace.current)) select(chosen, data.user.id);
  });

  function label(w: Workspace): string {
    const name = w.kind === "personal" ? t("workspace.personal") : w.name;
    return t("workspace.option", { name, role: t(ROLES[w.role]) });
  }

  function pick(event: Event) {
    const id = (event.currentTarget as HTMLSelectElement).value;
    const chosen = workspaces.find((w) => w.id === id);
    if (chosen) select(chosen, data.user.id);
  }

  async function addStudio(event: SubmitEvent) {
    event.preventDefault();
    error = null;
    try {
      const result = await createStudio(studioName.trim());
      if (typeof result === "string") {
        error = result;
        return;
      }
      added = [...added, result];
      select(result, data.user.id);
      studioName = "";
    } catch {
      error = errorKey(undefined);
    }
  }

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
    forget(); // after leaving the page, so it cannot choose again in between
  }
</script>

<p>{t("home.signed_in_as", { name: data.user.name })}</p>
<button type="button" onclick={signOut}>{t("auth.sign_out")}</button>

<label>
  {t("workspace.choose")}
  <select value={workspace.current?.id} onchange={pick}>
    {#each workspaces as w (w.id)}
      <option value={w.id}>{label(w)}</option>
    {/each}
  </select>
</label>

<form onsubmit={addStudio}>
  <label>
    {t("workspace.new_studio")}
    <input bind:value={studioName} required maxlength="100" />
  </label>
  <button type="submit">{t("workspace.create")}</button>
</form>

{#if error}<p role="alert">{t(error)}</p>{/if}
