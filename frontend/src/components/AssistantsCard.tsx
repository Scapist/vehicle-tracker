import { Button, Card, Code, CopyButton, Group, Stack, Text, TextInput } from "@mantine/core";
import { IconCheck, IconCopy, IconKey, IconRobot } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { day } from "../lib/format";
import { useMe, useUser } from "./AuthGate";
import { notifyError } from "./status";

type Token = components["schemas"]["TokenOut"];

function Copy({ value }: { value: string }) {
  return (
    <CopyButton value={value}>
      {({ copied, copy }) => (
        <Button size="compact-sm" variant="light" onClick={copy}
          leftSection={copied ? <IconCheck size={14} /> : <IconCopy size={14} />}>
          {copied ? "Copied" : "Copy"}
        </Button>
      )}
    </CopyButton>
  );
}

/** Access tokens for the MCP server, plus copy-paste setup for Claude Code and Claude Desktop. */
export function AssistantsCard() {
  const me = useMe().data;
  const user = useUser();
  const qc = useQueryClient();
  const enabled = !!me?.mcp_enabled;
  const tokens = useQuery({ queryKey: ["mcp-tokens"], queryFn: () => api<Token[]>("/mcp-tokens"), enabled,
    retry: false });
  const [name, setName] = useState("Claude Desktop");
  const [fresh, setFresh] = useState<string | null>(null);
  const url = `${window.location.origin}/mcp`;
  const token = fresh ?? "<your token>";

  async function create() {
    try {
      const t = await api<Token>("/mcp-tokens", { method: "POST", json: { name: name.trim() } });
      setFresh(t.token ?? null);
      await qc.invalidateQueries({ queryKey: ["mcp-tokens"] });
    } catch (e) {
      notifyError(e);
    }
  }
  async function revoke(id: number) {
    try {
      await api(`/mcp-tokens/${id}`, { method: "DELETE" });
      await qc.invalidateQueries({ queryKey: ["mcp-tokens"] });
    } catch (e) {
      notifyError(e);
    }
  }

  const desktop = JSON.stringify({
    mcpServers: {
      tracker: {
        command: "npx",
        args: ["mcp-remote", url, ...(url.startsWith("http://") ? ["--allow-http"] : []), "--header",
          `Authorization:Bearer ${token}`],
      },
    },
  }, null, 2);

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group gap="xs">
          <IconRobot size={18} />
          <Text fw={600}>AI assistants (MCP)</Text>
        </Group>
        {!enabled ? (
          <Text size="sm" c="dimmed">
            Let an assistant such as Claude read your vehicles and log km, services and receipts for you. It's turned
            off on this server{user.is_owner ? <>: set <Code>MCP_ENABLED=true</Code> in .env and restart</> : ""}.
          </Text>
        ) : tokens.isError ? (
          <Text size="sm" c="dimmed">Only the owner of this server can connect AI assistants.</Text>
        ) : (
          <>
            <Text size="sm" c="dimmed">
              A token lets an assistant read your vehicles and log km, services and receipts as you. It can't edit or
              delete anything. Anyone with the token can do the same, so keep it private and revoke it if it leaks.
            </Text>
            {(tokens.data ?? []).map((t) => (
              <Group key={t.id} justify="space-between" wrap="nowrap">
                <div>
                  <Text size="sm" fw={500}>{t.name}</Text>
                  <Text size="xs" c="dimmed">
                    Created {day(t.created_at.slice(0, 10))} ·{" "}
                    {t.last_used_at ? `last used ${day(t.last_used_at.slice(0, 10))}` : "never used"}
                  </Text>
                </div>
                <Button size="compact-sm" variant="subtle" color="red" onClick={() => revoke(t.id)}>Revoke</Button>
              </Group>
            ))}
            <Group align="flex-end" gap="xs">
              <TextInput label="New token for" value={name} maxLength={80} style={{ flex: "1 1 200px" }}
                onChange={(e) => setName(e.currentTarget.value)} />
              <Button leftSection={<IconKey size={16} />} onClick={create} disabled={!name.trim()}>Create token</Button>
            </Group>
            {fresh && (
              <Stack gap={6}>
                <Text size="sm" fw={500}>Copy it now: it won't be shown again.</Text>
                <Group gap="xs" wrap="nowrap">
                  <Code style={{ overflowWrap: "anywhere" }} data-testid="new-token">{fresh}</Code>
                  <Copy value={fresh} />
                </Group>
              </Stack>
            )}
            <Text size="sm" fw={500}>Claude Code</Text>
            <Code block style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {`claude mcp add --scope user --transport http tracker ${url} --header "Authorization: Bearer ${token}"`}
            </Code>
            <Text size="sm" fw={500}>Claude Desktop (claude_desktop_config.json)</Text>
            <Code block style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{desktop}</Code>
          </>
        )}
      </Stack>
    </Card>
  );
}
