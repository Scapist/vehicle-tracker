import {
  Autocomplete, Badge, Button, Card, Group, Modal, NumberInput, Select, Stack, Text, Textarea, TextInput, Title,
} from "@mantine/core";
import { DateInput } from "@mantine/dates";
import { useMediaQuery } from "@mantine/hooks";
import { IconPlus } from "@tabler/icons-react";
import dayjs from "dayjs";
import { useState } from "react";

import { api } from "../api/client";
import { useApiMutation, useRecurringCosts } from "../api/hooks";
import type { RecurringCost } from "../api/types";
import { day, isoDate, money, toCents } from "../lib/format";
import { notifyError, notifyUndo } from "./status";

export const CATEGORIES = ["Insurance", "Registration", "Financing", "Parking", "Other"];
const EVERY: Record<number, string> = { 1: "month", 3: "3 months", 6: "6 months", 12: "year" };

const isActive = (c: RecurringCost) => c.next_date != null;

/** What a payment costs per month on average (a yearly $1,200 counts as $100). */
export const perMonth = (cs: RecurringCost[]) =>
  cs.filter(isActive).reduce((sum, c) => sum + c.amount_cents / c.every_months, 0);

export function PaymentsTab({ vehicleId }: { vehicleId: number }) {
  const costs = useRecurringCosts(vehicleId);
  const [editing, setEditing] = useState<RecurringCost | "new" | null>(null);
  const [changing, setChanging] = useState<RecurringCost | null>(null);
  const active = (costs.data ?? []).filter(isActive);
  const ended = (costs.data ?? []).filter((c) => !isActive(c));

  async function remove(c: RecurringCost) {
    try {
      await api(`/recurring-costs/${c.id}`, { method: "DELETE" });
      notifyUndo(`Removed “${c.name}”`, async () => {
        const { id: _id, vehicle_id: _v, next_date: _n, ...body } = c;
        await api(`/vehicles/${vehicleId}/recurring-costs`, { method: "POST", json: body });
        costs.refetch();
      });
      costs.refetch();
    } catch (e) { notifyError(e); }
  }

  const row = (c: RecurringCost) => (
    <Card key={c.id} withBorder padding="sm">
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <div>
            <Group gap="xs">
              <Text fw={600}>{c.name}</Text>
              <Badge variant="light" size="sm">{c.category}</Badge>
            </Group>
            <Text size="sm" c="dimmed">
              {money(c.amount_cents)} / {EVERY[c.every_months]}
              {c.next_date ? ` · next ${day(c.next_date)}` : c.end_date ? ` · ended ${day(c.end_date)}` : ""}
              {c.next_date && c.end_date ? ` · last by ${day(c.end_date)}` : ""}
              {c.remind_days != null ? ` · reminder ${c.remind_days} days before` : ""}
            </Text>
          </div>
          <Text fw={700} style={{ whiteSpace: "nowrap" }}>{money(c.amount_cents)}</Text>
        </Group>
        <Group gap="xs">
          <Button size="compact-sm" variant="default" onClick={() => setEditing(c)}>Edit</Button>
          {isActive(c) && <Button size="compact-sm" variant="default" onClick={() => setChanging(c)}>Change amount…</Button>}
          <Button size="compact-sm" variant="subtle" color="red" onClick={() => remove(c)}>Remove</Button>
        </Group>
      </Stack>
    </Card>
  );

  return (
    <Stack>
      <Group justify="space-between">
        <div>
          <Title order={4}>Recurring payments</Title>
          {active.length > 0 && (
            <Text size="sm" c="dimmed">About {money(Math.round(perMonth(active)))} a month in fixed costs</Text>
          )}
        </div>
        <Button size="compact-md" leftSection={<IconPlus size={14} />} onClick={() => setEditing("new")}>Add payment</Button>
      </Group>
      <Text size="sm" c="dimmed">
        Payments taken automatically, like insurance, financing or registration. Each one counts toward your
        spending on its date, with nothing to confirm.
      </Text>
      {costs.data?.length === 0 && <Text c="dimmed">No recurring payments yet.</Text>}
      {active.map(row)}
      {ended.length > 0 && <Text size="sm" fw={600} c="dimmed" mt="sm">Ended (kept for reports)</Text>}
      {ended.map(row)}
      {editing && <PaymentModal vehicleId={vehicleId} cost={editing === "new" ? null : editing}
        onClose={() => setEditing(null)} />}
      {changing && <ChangeAmountModal cost={changing} onClose={() => setChanging(null)} />}
    </Stack>
  );
}

function PaymentModal({ vehicleId, cost, onClose }: { vehicleId: number; cost: RecurringCost | null; onClose: () => void }) {
  const mobile = useMediaQuery("(max-width: 48em)");
  const [name, setName] = useState(cost?.name ?? "");
  const [category, setCategory] = useState(cost?.category ?? "Insurance");
  const [amount, setAmount] = useState<number | string>(cost ? cost.amount_cents / 100 : "");
  const [every, setEvery] = useState(String(cost?.every_months ?? 1));
  const [start, setStart] = useState<Date | null>(cost ? dayjs(cost.start_date).toDate() : null);
  const [end, setEnd] = useState<Date | null>(cost?.end_date ? dayjs(cost.end_date).toDate() : null);
  const [remind, setRemind] = useState<number | string>(cost?.remind_days ?? 30);
  const [notes, setNotes] = useState(cost?.notes ?? "");
  const yearly = every === "12";
  const save = useApiMutation((b: object) => cost
    ? api(`/recurring-costs/${cost.id}`, { method: "PATCH", json: b })
    : api(`/vehicles/${vehicleId}/recurring-costs`, { method: "POST", json: b }));

  async function submit() {
    try {
      await save.mutateAsync({
        name: name.trim(), category: category.trim() || "Other", amount_cents: toCents(amount),
        every_months: Number(every), start_date: isoDate(start), end_date: end ? isoDate(end) : null,
        remind_days: yearly && remind !== "" ? Number(remind) : null, notes: notes.trim() || null,
      });
      onClose();
    } catch (e) { notifyError(e); }
  }

  return (
    <Modal opened onClose={onClose} title={cost ? "Edit payment" : "Add payment"} fullScreen={!!mobile}>
      <Stack>
        <TextInput label="Name" placeholder="e.g. Car insurance, Lease, SAAQ" value={name}
          onChange={(e) => setName(e.currentTarget.value)} />
        <Autocomplete label="Category" data={CATEGORIES} value={category} onChange={setCategory} />
        <Group grow align="flex-start">
          <NumberInput label="Amount" prefix="$" decimalScale={2} thousandSeparator="," min={0} value={amount}
            onChange={setAmount} />
          <Select label="Every" allowDeselect={false} value={every} onChange={(v) => v && setEvery(v)}
            data={[{ value: "1", label: "Month" }, { value: "3", label: "3 months" },
              { value: "6", label: "6 months" }, { value: "12", label: "Year" }]} />
        </Group>
        <Group grow align="flex-start">
          <DateInput label="First payment" value={start} onChange={setStart} />
          <DateInput label="Last payment (optional)" value={end} onChange={setEnd} clearable minDate={start ?? undefined} />
        </Group>
        {cost && <Text size="xs" c="dimmed">Changing the amount here rewrites past payments too. To start a new price
          from a date, use “Change amount…”.</Text>}
        {yearly && (
          <NumberInput label="Remind me this many days before (empty for no reminder)" value={remind}
            onChange={setRemind} min={0} max={365} />
        )}
        <Textarea label="Notes" autosize minRows={2} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
        <Button onClick={submit} loading={save.isPending} disabled={!name.trim() || toCents(amount) <= 0 || !start}>
          Save
        </Button>
      </Stack>
    </Modal>
  );
}

function ChangeAmountModal({ cost, onClose }: { cost: RecurringCost; onClose: () => void }) {
  const [amount, setAmount] = useState<number | string>(cost.amount_cents / 100);
  const [from, setFrom] = useState<Date | null>(cost.next_date ? dayjs(cost.next_date).toDate() : new Date());
  const change = useApiMutation((b: object) => api(`/recurring-costs/${cost.id}/change-amount`, { method: "POST", json: b }));
  async function submit() {
    try {
      await change.mutateAsync({ amount_cents: toCents(amount), from_date: isoDate(from) });
      onClose();
    } catch (e) { notifyError(e); }
  }
  return (
    <Modal opened onClose={onClose} title={`New amount for ${cost.name}`}>
      <Stack>
        <NumberInput label="New amount" prefix="$" decimalScale={2} thousandSeparator="," min={0} value={amount}
          onChange={setAmount} data-autofocus />
        <DateInput label="Starting with the payment on" value={from} onChange={setFrom}
          minDate={dayjs(cost.start_date).add(1, "day").toDate()} />
        <Text size="xs" c="dimmed">Payments before this date keep the old amount of {money(cost.amount_cents)}.</Text>
        <Button onClick={submit} loading={change.isPending} disabled={!from || toCents(amount) <= 0}>Save</Button>
      </Stack>
    </Modal>
  );
}
