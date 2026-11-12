import { Button, Card, Group, Modal, Progress, Select, Stack, Text } from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { api } from "../api/client";
import { useDateItems, useInvalidate, useTireSets } from "../api/hooks";
import type { Service, StatusItem } from "../api/types";
import { notifyError, notifyUndo, statusOf, StatusBadge } from "./status";

/** One reminder or date item with its progress bar and quick actions. */
export function ItemCard({ item, compact }: { item: StatusItem; compact?: boolean }) {
  const s = statusOf(item.status);
  const invalidate = useInvalidate();
  const [askTires, tires] = useDisclosure(false);
  const dates = useDateItems(item.vehicle_id ?? undefined);
  const kind = item.kind === "date" ? dates.data?.find((d) => d.id === item.id)?.kind : undefined;
  const needsAction = item.status === "overdue" || item.status === "due_soon";

  async function doneRule() {
    try {
      const rec = await api<Service>(`/rules/${item.id}/done`, { method: "POST" });
      await invalidate();
      notifyUndo(`${item.title} logged as done today`, async () => {
        await api(`/services/${rec.id}`, { method: "DELETE" });
        await invalidate();
      });
    } catch (e) {
      notifyError(e);
    }
  }

  async function snooze() {
    try {
      await api(`/rules/${item.id}/snooze`, { method: "POST", json: { days: 7 } });
      await invalidate();
      notifyUndo(`${item.title} snoozed for 7 days (no alerts until then)`, async () => {
        await api(`/rules/${item.id}/snooze`, { method: "DELETE" });
        await invalidate();
      });
    } catch (e) {
      notifyError(e);
    }
  }

  async function doneDate(tireSetId?: number) {
    try {
      await api(`/date-items/${item.id}/done`, { method: "POST", json: { tire_set_id: tireSetId ?? null } });
      await invalidate();
      notifications.show({ color: "green", message: `${item.title}: done` });
    } catch (e) {
      notifyError(e);
    }
  }

  const isWinter = kind === "winter_install" || kind === "winter_remove";

  return (
    <Card withBorder padding="sm" radius="md">
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <div>
            <Text fw={600}>{item.title}</Text>
            <Text size="sm" c="dimmed">{item.detail}</Text>
          </div>
          <StatusBadge status={item.status} />
        </Group>
        {item.progress != null && !compact && (
          <Progress
            value={Math.min(100, item.progress * 100)}
            color={s.color}
            size="sm"
            aria-label={`${Math.round(item.progress * 100)}% of the interval used`}
          />
        )}
        {needsAction && !item.informational && item.kind !== "cost" && (
          <Group gap="xs">
            <Button size="compact-sm" onClick={item.kind === "rule" ? doneRule : isWinter ? tires.open : () => doneDate()}>
              {item.kind === "rule" ? "Done today" : "Mark done"}
            </Button>
            {item.kind === "rule" && (
              <Button size="compact-sm" variant="default" onClick={snooze}>Snooze 7 d</Button>
            )}
          </Group>
        )}
        {item.status === "unknown" && item.kind === "rule" && (
          <Button size="compact-sm" variant="light" onClick={doneRule}>Done today</Button>
        )}
      </Stack>
      {isWinter && item.vehicle_id && (
        <TirePicker opened={askTires} onClose={tires.close} vehicleId={item.vehicle_id}
          onPick={(id) => { tires.close(); doneDate(id); }} />
      )}
    </Card>
  );
}

function TirePicker({ opened, onClose, vehicleId, onPick }: {
  opened: boolean; onClose: () => void; vehicleId: number; onPick: (id: number) => void;
}) {
  const sets = useTireSets(vehicleId);
  const [value, setValue] = useState<string | null>(null);
  const mobile = useMediaQuery("(max-width: 48em)");
  return (
    <Modal opened={opened} onClose={onClose} title="Which tire set is on the car?" fullScreen={!!mobile}>
      <Stack>
        <Select
          data={(sets.data ?? []).filter((t) => !t.retired).map((t) => ({ value: String(t.id), label: `${t.label} (${t.season})` }))}
          value={value} onChange={setValue} placeholder="Pick a set" />
        <Button disabled={!value} onClick={() => onPick(Number(value))}>Confirm</Button>
      </Stack>
    </Modal>
  );
}
