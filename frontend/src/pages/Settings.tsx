import {
  Badge, Button, Card, Code, CopyButton, Group, Modal, PasswordInput, SegmentedControl, Stack, Text, TextInput, Title,
} from "@mantine/core";
import { useMantineColorScheme } from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconBrandTelegram, IconCheck, IconCopy, IconKey, IconLogout, IconPlus, IconUserPlus } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "../api/client";
import { useApiMutation, useServiceTypes, useVehicles } from "../api/hooks";
import type { components } from "../api/schema";
import { setSession, useUser } from "../components/AuthGate";
import { notifyError, notifyUndo } from "../components/status";
import { day } from "../lib/format";
import { AssistantsCard } from "../components/AssistantsCard";
import { ChatAppsCard } from "../components/ChatAppsCard";
import { AddVehicleModal } from "./Vehicles";

type Invite = components["schemas"]["InviteOut"];

export default function Settings() {
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const user = useUser();
  const vehicles = useVehicles();
  const [adding, add] = useDisclosure(false);
  const archive = useApiMutation((a: { id: number; archived: boolean }) =>
    api(`/vehicles/${a.id}`, { method: "PATCH", json: { archived: a.archived } }));
  return (
    <Stack maw={720}>
      <Title order={2}>Settings</Title>
      <AccountCard />
      <Card withBorder>
        <Stack>
          <Text fw={600}>Appearance</Text>
          <SegmentedControl value={colorScheme} onChange={(v) => setColorScheme(v as "light" | "dark" | "auto")}
            data={[{ value: "auto", label: "Match system" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />
        </Stack>
      </Card>
      <Card withBorder>
        <Stack>
          <Group justify="space-between">
            <Text fw={600}>Vehicles</Text>
            <Button size="compact-md" leftSection={<IconPlus size={14} />} onClick={add.open}>Add</Button>
          </Group>
          {vehicles.data?.length === 0 && <Text size="sm" c="dimmed">No vehicles yet.</Text>}
          {vehicles.data?.map((v) => (
            <Group key={v.id} justify="space-between">
              <Text>{v.nickname} <Text span c="dimmed">({v.year} {v.make} {v.model})</Text></Text>
              <Button size="compact-sm" variant="default" onClick={() => {
                archive.mutate({ id: v.id, archived: true });
                notifyUndo(`${v.nickname} archived`, () => archive.mutateAsync({ id: v.id, archived: false }));
              }}>Archive</Button>
            </Group>
          ))}
        </Stack>
      </Card>
      <ServicesCard />
      <ChatAppsCard />
      <AssistantsCard />
      {user.is_owner && <InvitesCard />}
      <AddVehicleModal opened={adding} onClose={add.close} />
    </Stack>
  );
}

function AccountCard() {
  const user = useUser();
  const qc = useQueryClient();
  const [pwOpen, pw] = useDisclosure(false);
  async function signOut(everywhere: boolean) {
    try {
      await api(everywhere ? "/auth/logout-everywhere" : "/auth/logout", { method: "POST" });
      setSession(qc, { user: null, setup_required: false, channels_available: [], mcp_enabled: false });
    } catch (e) {
      notifyError(e);
    }
  }
  return (
    <Card withBorder>
      <Stack>
        <Group justify="space-between" align="flex-start">
          <div>
            <Group gap="xs">
              <Text fw={600}>{user.name}</Text>
              {user.is_owner && <Badge variant="light" size="sm">Owner</Badge>}
            </Group>
            <Text size="sm" c="dimmed">{user.email}</Text>
          </div>
          <Button variant="default" leftSection={<IconLogout size={16} />} onClick={() => signOut(false)}>Sign out</Button>
        </Group>
        <Group gap="xs">
          <Button size="compact-sm" variant="light" leftSection={<IconKey size={14} />} onClick={pw.open}>
            Change password
          </Button>
          <Button size="compact-sm" variant="subtle" color="gray" onClick={() => signOut(true)}>
            Sign out on all devices
          </Button>
        </Group>
      </Stack>
      <ChangePassword opened={pwOpen} onClose={pw.close} />
    </Card>
  );
}

function ChangePassword({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const mobile = useMediaQuery("(max-width: 48em)");
  const [f, setF] = useState({ current: "", next: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mismatch = f.confirm !== "" && f.confirm !== f.next;
  const tooShort = f.next !== "" && f.next.length < 10;
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password", { method: "POST", json: { current_password: f.current, new_password: f.next } });
      notifications.show({ color: "green", message: "Password changed. Other devices were signed out." });
      setF({ current: "", next: "", confirm: "" });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal opened={opened} onClose={onClose} title="Change password" fullScreen={!!mobile}>
      <Stack>
        <PasswordInput label="Current password" value={f.current} autoComplete="current-password" data-autofocus
          onChange={(e) => setF({ ...f, current: e.currentTarget.value })} error={error} />
        <PasswordInput label="New password" value={f.next} autoComplete="new-password"
          description="At least 10 characters" error={tooShort ? "At least 10 characters" : undefined}
          onChange={(e) => setF({ ...f, next: e.currentTarget.value })} />
        <PasswordInput label="Confirm new password" value={f.confirm} autoComplete="new-password"
          error={mismatch ? "Passwords don't match" : undefined}
          onChange={(e) => setF({ ...f, confirm: e.currentTarget.value })} />
        <Button onClick={submit} loading={busy} disabled={!f.current || !f.next || !f.confirm || mismatch || tooShort}>
          Change password
        </Button>
      </Stack>
    </Modal>
  );
}

function InvitesCard() {
  const qc = useQueryClient();
  const invites = useQuery({ queryKey: ["invites"], queryFn: () => api<Invite[]>("/auth/invites") });
  const [fresh, setFresh] = useState<string | null>(null);
  async function create() {
    try {
      const inv = await api<Invite>("/auth/invites", { method: "POST" });
      setFresh(`${window.location.origin}${inv.link}`);
      await qc.invalidateQueries({ queryKey: ["invites"] });
    } catch (e) {
      notifyError(e);
    }
  }
  async function revoke(id: number) {
    try {
      await api(`/auth/invites/${id}`, { method: "DELETE" });
      await qc.invalidateQueries({ queryKey: ["invites"] });
    } catch (e) {
      notifyError(e);
    }
  }
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={600}>Invite people</Text>
          <Button size="compact-sm" leftSection={<IconUserPlus size={14} />} onClick={create}>New invite link</Button>
        </Group>
        <Text size="sm" c="dimmed">
          Each link creates one account with its own separate vehicles and data, and expires after 7 days.
        </Text>
        {fresh && (
          <Stack gap={6}>
            <Text size="sm">Send this link to the person you're inviting. It's only shown once.</Text>
            <Group gap="xs" wrap="nowrap">
              <TextInput value={fresh} readOnly style={{ flex: 1 }} onFocus={(e) => e.currentTarget.select()} />
              <CopyButton value={fresh}>
                {({ copied, copy }) => (
                  <Button variant="light" onClick={copy} leftSection={copied ? <IconCheck size={14} /> : <IconCopy size={14} />}>
                    {copied ? "Copied" : "Copy"}
                  </Button>
                )}
              </CopyButton>
            </Group>
          </Stack>
        )}
        {invites.data?.map((inv) => (
          <Group key={inv.id} justify="space-between">
            <Text size="sm">
              {inv.used ? `Used by ${inv.used_by_name ?? "someone"}` : `Pending, expires ${day(inv.expires_at)}`}
              <Text span c="dimmed"> · created {day(inv.created_at)}</Text>
            </Text>
            {!inv.used && (
              <Button size="compact-xs" variant="subtle" color="red" onClick={() => revoke(inv.id)}>Revoke</Button>
            )}
          </Group>
        ))}
      </Stack>
    </Card>
  );
}

function ServicesCard() {
  const types = useServiceTypes();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null);
  const custom = (types.data ?? []).filter((t) => t.custom);
  const refresh = () => qc.invalidateQueries();
  async function add() {
    try {
      await api("/service-types", { method: "POST", json: { name } });
      setName("");
      await refresh();
    } catch (e) { notifyError(e); }
  }
  async function rename() {
    if (!renaming) return;
    try {
      await api(`/service-types/${renaming.id}`, { method: "PATCH", json: { name: renaming.name } });
      setRenaming(null);
      await refresh();
    } catch (e) { notifyError(e); }
  }
  async function remove(id: number) {
    try {
      await api(`/service-types/${id}`, { method: "DELETE" });
      await refresh();
    } catch (e) { notifyError(e); }
  }
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Text fw={600}>Your services</Text>
        <Text size="sm" c="dimmed">
          Services that aren't in the built-in list. You can also add one while logging: type its name in
          “What was done?”. Only you see them.
        </Text>
        {custom.length === 0 && <Text size="sm" c="dimmed">None yet.</Text>}
        {custom.map((t) => (
          <Group key={t.id} justify="space-between" wrap="nowrap">
            <Text>{t.name}</Text>
            <Group gap="xs" wrap="nowrap">
              <Button size="compact-sm" variant="default" onClick={() => setRenaming({ id: t.id, name: t.name })}>Rename</Button>
              <Button size="compact-sm" variant="subtle" color="red" onClick={() => remove(t.id)}>Delete</Button>
            </Group>
          </Group>
        ))}
        <Group gap="xs" wrap="nowrap">
          <TextInput placeholder="e.g. Wheel alignment" aria-label="New service" style={{ flex: 1 }} value={name}
            onChange={(e) => setName(e.currentTarget.value)} onKeyDown={(e) => e.key === "Enter" && name.trim() && add()} />
          <Button leftSection={<IconPlus size={14} />} onClick={add} disabled={!name.trim()}>Add</Button>
        </Group>
      </Stack>
      <Modal opened={!!renaming} onClose={() => setRenaming(null)} title="Rename service">
        <Stack>
          <TextInput label="Name" data-autofocus value={renaming?.name ?? ""}
            onChange={(e) => { const v = e.currentTarget.value; setRenaming((r) => (r ? { ...r, name: v } : r)); }} />
          <Text size="xs" c="dimmed">Past services and reports use the new name too.</Text>
          <Button onClick={rename} disabled={!renaming?.name.trim()}>Save</Button>
        </Stack>
      </Modal>
    </Card>
  );
}
