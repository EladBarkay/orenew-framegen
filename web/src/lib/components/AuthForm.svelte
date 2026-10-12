<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";

  import { page } from "$app/state";

  import { api } from "#lib/api.ts";
  import { errorKey } from "#lib/errors.ts";
  import { afterSignIn, withNext } from "#lib/session.ts";
  import { parts, t, type MessageKey } from "#lib/i18n.svelte.ts";

  /** One form for both: signing up also asks for a name. */
  let { mode }: { mode: "signin" | "signup" } = $props();

  let email = $state("");
  let password = $state("");
  let name = $state("");
  let error: MessageKey | null = $state(null);
  let busy = $state(false);

  const next = $derived(page.url.searchParams.get("next"));

  /** After signing in: back to the page asked for, or home if that cannot be shown. */
  async function goOn() {
    try {
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- afterSignIn resolves
      await goto(afterSignIn(next, page.url));
    } catch {
      await goto(resolve("/"));
    }
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = null;
    try {
      const result =
        mode === "signup"
          ? await api.POST("/v1/auth/signup", { body: { email, password, name: name.trim() } })
          : await api.POST("/v1/auth/signin", { body: { email, password } });
      if (result.response.ok) {
        await goOn();
        return;
      }
      error = errorKey(result.error);
    } catch {
      error = errorKey(undefined);
    } finally {
      busy = false;
    }
  }
</script>

<form onsubmit={submit}>
  <h2>{t(mode === "signup" ? "auth.sign_up" : "auth.sign_in")}</h2>
  {#if mode === "signup"}
    <label>
      {t("auth.name")}
      <input bind:value={name} required maxlength="100" autocomplete="name" />
    </label>
  {/if}
  <label>
    {t("auth.email")}
    <input bind:value={email} type="email" required autocomplete="email" />
  </label>
  <label>
    {t("auth.password")}
    <input
      bind:value={password}
      type="password"
      required
      minlength={mode === "signup" ? 10 : undefined}
      maxlength="200"
      autocomplete={mode === "signup" ? "new-password" : "current-password"}
    />
    {#if mode === "signup"}<small>{t("auth.password_hint")}</small>{/if}
  </label>
  {#if error}<p role="alert">{t(error)}</p>{/if}
  <button type="submit" disabled={busy}>
    {t(mode === "signup" ? "auth.sign_up" : "auth.sign_in")}
  </button>
  <!-- eslint-disable svelte/no-navigation-without-resolve -- the href is withNext(resolve()) -->
  <p>
    {#each parts(mode === "signup" ? "auth.have_account" : "auth.no_account") as part, index (index)}
      {#if "text" in part}{part.text}{:else if part.slot === "link"}<a
          href={withNext(resolve(mode === "signup" ? "/signin" : "/signup"), next)}
          >{t(mode === "signup" ? "auth.sign_in" : "auth.sign_up")}</a
        >{/if}
    {/each}
  </p>
  <!-- eslint-enable svelte/no-navigation-without-resolve -->
</form>

<style>
  form {
    display: grid;
    gap: 1rem;
    max-inline-size: 24rem;
  }

  label {
    display: grid;
    gap: 0.25rem;
  }
</style>
