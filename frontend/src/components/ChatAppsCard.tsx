import { Badge, Button, Card, Code, CopyButton, Group, Select, Stack, Text } from "@mantine/core";
import { IconBrandDiscord, IconBrandTelegram, IconCheck, IconCopy } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { useMe, useUser } from "./AuthGate";
import { notifyError } from "./status";

type LinkCode = components["schemas"]["LinkCode"];

const APPS = {
  telegram: { label: "Telegram", Icon: IconBrandTelegram, cmd: "/link" },
  discord: { label: "Discord", Icon: IconBrandDiscord, cmd: "!link" },
} as const;
type App = keyof typeof APPS;

/** Telegram and Discord: connect with a one-time code, and pick where alerts go when both are connected. */
export function ChatAppsCard() {
  const me = useMe().data;
  const user = useUser();
  const qc = useQueryClient();
  const [link, setLink] = useState<{ app: App; code: string } | null>(null);
  const available = (me?.channels_available ?? []).filter((a): a is App => a in APPS);
  const linked = (a: App) => (a === "telegram" ? user.telegram_linked : !!user.discord_linked);
  const linkedApps = available.filter(linked);
  const refresh = () => qc.invalidateQueries({ queryKey: ["auth-me"] });

  async function run(fn: () => Promise<unknown>) {
    try {
      await fn();
    } catch (e) {
      notifyError(e);
    }
  }
  const connect = (app: App) => run(async () => {
    const c = await api<LinkCode>("/auth/link-code", { method: "POST" });
    setLink({ app, code: c.code });
  });
  const disconnect = (app: App) => run(async () => {
    await api(`/auth/${app}`, { method: "DELETE" });
    await refresh();
  });
  const prefer = (app: string) => run(async () => {
    await api("/auth/alert-channel", { method: "PUT", json: { channel: app } });
    await refresh();
  });

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Text fw={600}>Chat apps</Text>
        <Text size="sm" c="dimmed">
          Get alerts for your vehicles and log mileage by texting the bot. You can text your km to any connected app.
        </Text>
        {available.length === 0 && (
          <Text size="sm">
            No chat app is set up on this server yet (<Code>TELEGRAM_BOT_TOKEN</Code> or <Code>DISCORD_BOT_TOKEN</Code> in
            .env).
          </Text>
        )}
        {available.map((app) => {
          const { label, Icon, cmd } = APPS[app];
          const command = link ? `${cmd} ${link.code}` : "";
          return (
            <Stack key={app} gap={6}>
              <Group justify="space-between">
                <Group gap="xs">
                  <Icon size={18} />
                  <Text fw={500}>{label}</Text>
                  {linked(app)
                    ? <Badge color="green" variant="light" size="sm">Connected</Badge>
                    : <Badge color="gray" variant="light" size="sm">Not connected</Badge>}
                </Group>
                {linked(app)
                  ? <Button size="compact-sm" variant="subtle" color="red" onClick={() => disconnect(app)}>Disconnect</Button>
                  : <Button size="compact-sm" onClick={() => connect(app)} aria-label={`Connect ${label}`}>Connect</Button>}
              </Group>
              {link?.app === app && !linked(app) && (
                <Stack gap={6}>
                  <Text size="sm">
                    Send this to the bot in {label}{app === "discord" ? " as a direct message" : ""} (valid for 10 minutes):
                  </Text>
                  <Group gap="xs">
                    <Code fz="md">{command}</Code>
                    <CopyButton value={command}>
                      {({ copied, copy }) => (
                        <Button size="compact-sm" variant="light" onClick={copy}
                          leftSection={copied ? <IconCheck size={14} /> : <IconCopy size={14} />}>
                          {copied ? "Copied" : "Copy"}
                        </Button>
                      )}
                    </CopyButton>
                  </Group>
                  <Button size="compact-sm" variant="subtle" w="fit-content" onClick={refresh}>I've sent it</Button>
                </Stack>
              )}
            </Stack>
          );
        })}
        {linkedApps.length > 1 && (
          <Select label="Send alerts to" w={220} allowDeselect={false}
            data={linkedApps.map((a) => ({ value: a, label: APPS[a].label }))}
            value={linkedApps.includes(user.alert_channel as App) ? user.alert_channel : linkedApps[0]}
            onChange={(v) => v && prefer(v)} />
        )}
      </Stack>
    </Card>
  );
}
