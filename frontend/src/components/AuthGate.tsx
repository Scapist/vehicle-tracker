import {
  Alert, Anchor, Button, Card, Center, Loader, PasswordInput, Stack, Text, TextInput, ThemeIcon, Title,
} from "@mantine/core";
import { IconCar } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { api, ApiError } from "../api/client";
import type { components } from "../api/schema";

export type Me = components["schemas"]["Me"];
export type User = components["schemas"]["UserOut"];
type Screen = "login" | "setup" | "signup";

/** Switch the signed-in state and drop every cached piece of data from the previous session. */
export function setSession(qc: ReturnType<typeof useQueryClient>, me: Me) {
  qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth-me" });
  qc.setQueryData<Me>(["auth-me"], me);
}

export const useMe = () =>
  useQuery({ queryKey: ["auth-me"], queryFn: () => api<Me>("/auth/me"), staleTime: 60_000, retry: false });

/** The signed-in user. Only use inside AuthGate. */
export const useUser = () => useMe().data?.user as User;

const inviteFromUrl = () => new URLSearchParams(window.location.search).get("invite");

/** Shows setup / sign-up / login until the server says this browser is signed in. */
export function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe();
  const qc = useQueryClient();

  useEffect(() => {
    const onExpired = () => qc.setQueryData<Me>(["auth-me"], (m) => (m ? { ...m, user: null } : m));
    window.addEventListener("auth:required", onExpired);
    return () => window.removeEventListener("auth:required", onExpired);
  }, [qc]);

  if (me.isLoading) return <Center h="100vh"><Loader /></Center>;
  if (me.error) {
    return <Center h="100vh"><Text c="red">Can't reach the server. Check that it's running.</Text></Center>;
  }
  if (me.data?.user) {
    if (window.location.pathname === "/signup") window.history.replaceState(null, "", "/");
    return <>{children}</>;
  }
  const invite = inviteFromUrl();
  const start: Screen = me.data?.setup_required ? "setup" : invite ? "signup" : "login";
  return <AuthScreens start={start} invite={invite} />;
}

function Frame({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <Center mih="100vh" p="md">
      <Card withBorder radius="md" padding="xl" w="100%" maw={400}>
        <Stack>
          <Stack align="center" gap={4}>
            <ThemeIcon variant="light" size={48} radius="xl"><IconCar size={28} /></ThemeIcon>
            <Title order={3}>{title}</Title>
            {subtitle && <Text size="sm" c="dimmed" ta="center">{subtitle}</Text>}
          </Stack>
          {children}
        </Stack>
      </Card>
    </Center>
  );
}

function AuthScreens({ start, invite }: { start: Screen; invite: string | null }) {
  const qc = useQueryClient();
  const [screen, setScreen] = useState<Screen>(start);
  const [f, setF] = useState({ name: "", email: "", password: "", confirm: "", code: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF({ ...f, [k]: e.currentTarget.value });
  const creating = screen !== "login";
  const mismatch = creating && f.confirm !== "" && f.confirm !== f.password;
  const tooShort = creating && f.password !== "" && f.password.length < 10;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (creating && (mismatch || tooShort)) return;
    setBusy(true);
    setError(null);
    try {
      const account = { name: f.name, email: f.email, password: f.password };
      const me = screen === "login"
        ? await api<Me>("/auth/login", { method: "POST", json: { email: f.email, password: f.password } })
        : screen === "setup"
          ? await api<Me>("/auth/setup", { method: "POST", json: { ...account, setup_code: f.code } })
          : await api<Me>("/auth/signup", { method: "POST", json: { ...account, invite } });
      setSession(qc, me);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the server");
      setF((x) => ({ ...x, password: screen === "login" ? "" : x.password }));
    } finally {
      setBusy(false);
    }
  }

  const heading = {
    login: { title: "Sign in", subtitle: "Vehicle Tracker" },
    setup: { title: "Create the owner account",
      subtitle: "First time here. Use the setup code printed in the server log (docker compose logs)." },
    signup: { title: "Create your account", subtitle: "You've been invited to Vehicle Tracker." },
  }[screen];

  return (
    <Frame {...heading}>
      <form onSubmit={submit}>
        <Stack>
          {error && <Alert color="red" variant="light">{error}</Alert>}
          {screen === "setup" && (
            <TextInput label="Setup code" value={f.code} onChange={set("code")} autoComplete="off"
              styles={{ input: { textTransform: "uppercase", letterSpacing: 2 } }} required />
          )}
          {creating && <TextInput label="Your name" value={f.name} onChange={set("name")} autoComplete="name" required />}
          <TextInput label="Email" type="email" value={f.email} onChange={set("email")} autoComplete="email"
            data-autofocus autoFocus={screen === "login"} required />
          <PasswordInput label="Password" value={f.password} onChange={set("password")} required
            autoComplete={creating ? "new-password" : "current-password"}
            description={creating ? "At least 10 characters. A few random words works well." : undefined}
            error={tooShort ? "At least 10 characters" : undefined} />
          {creating && (
            <PasswordInput label="Confirm password" value={f.confirm} onChange={set("confirm")} required
              autoComplete="new-password" error={mismatch ? "Passwords don't match" : undefined} />
          )}
          <Button type="submit" loading={busy}
            disabled={!f.email || !f.password || (creating && (!f.name || !f.confirm || mismatch || tooShort))}>
            {screen === "login" ? "Sign in" : "Create account"}
          </Button>
          {screen === "login" && (
            <Text size="xs" c="dimmed" ta="center">
              New here? Ask the owner for an invite link.
            </Text>
          )}
          {screen === "signup" && (
            <Text size="sm" ta="center">
              Already have an account? <Anchor component="button" type="button" onClick={() => setScreen("login")}>Sign in</Anchor>
            </Text>
          )}
        </Stack>
      </form>
    </Frame>
  );
}
