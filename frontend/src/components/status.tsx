import { Badge, Button, Group, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconAlertOctagon, IconAlertTriangle, IconCircleCheck, IconHelpCircle,
} from "@tabler/icons-react";
import type { ReactNode } from "react";

export const STATUS = {
  overdue: { color: "red", label: "Overdue", icon: IconAlertOctagon },
  due_soon: { color: "orange", label: "Due soon", icon: IconAlertTriangle },
  ok: { color: "green", label: "OK", icon: IconCircleCheck },
  unknown: { color: "gray", label: "Unknown", icon: IconHelpCircle },
} as const;

export type StatusKey = keyof typeof STATUS;

export const statusOf = (s: string) => STATUS[(s in STATUS ? s : "unknown") as StatusKey];

/** Colour + icon + plain word, never colour alone. */
export function StatusBadge({ status }: { status: string }) {
  const s = statusOf(status);
  const Icon = s.icon;
  return (
    <Badge color={s.color} variant="light" leftSection={<Icon size={14} />} style={{ flexShrink: 0 }}>
      {s.label}
    </Badge>
  );
}

export function notifyError(e: unknown) {
  notifications.show({ color: "red", title: "That didn't work", message: e instanceof Error ? e.message : String(e) });
}

/** Undo toast instead of a confirm dialog. */
export function notifyUndo(message: ReactNode, onUndo: () => Promise<unknown> | void) {
  const id = `undo-${Date.now()}`;
  notifications.show({
    id,
    color: "green",
    autoClose: 8000,
    message: (
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm">{message}</Text>
        <Button
          size="compact-sm"
          variant="light"
          onClick={async () => {
            notifications.hide(id);
            try {
              await onUndo();
              notifications.show({ message: "Undone", color: "gray" });
            } catch (e) {
              notifyError(e);
            }
          }}
        >
          Undo
        </Button>
      </Group>
    ),
  });
}
