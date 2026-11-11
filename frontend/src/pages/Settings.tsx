import { Button, Card, Code, Group, SegmentedControl, Stack, Text, Title } from "@mantine/core";
import { useMantineColorScheme } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconPlus } from "@tabler/icons-react";

import { api } from "../api/client";
import { useApiMutation, useVehicles } from "../api/hooks";
import { notifyUndo } from "../components/status";
import { AddVehicleModal } from "./Vehicles";

export default function Settings() {
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const vehicles = useVehicles();
  const [adding, add] = useDisclosure(false);
  const archive = useApiMutation((a: { id: number; archived: boolean }) =>
    api(`/vehicles/${a.id}`, { method: "PATCH", json: { archived: a.archived } }));
  return (
    <Stack maw={720}>
      <Title order={2}>Settings</Title>
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
      <Card withBorder>
        <Stack gap="xs">
          <Text fw={600}>Telegram</Text>
          <Text size="sm" c="dimmed">
            Alerts and the mileage bot are configured in <Code>.env</Code>: set <Code>NOTIFIER=telegram</Code>,{" "}
            <Code>TELEGRAM_BOT_TOKEN</Code> and <Code>TELEGRAM_ALLOWED_CHAT_IDS</Code>, then restart. See the README.
          </Text>
        </Stack>
      </Card>
      <AddVehicleModal opened={adding} onClose={add.close} />
    </Stack>
  );
}
