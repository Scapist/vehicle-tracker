import {
  Anchor, Badge, Button, Card, Drawer, Group, Image, NumberInput, Stack, Table, Text, Textarea, TextInput,
  UnstyledButton,
} from "@mantine/core";
import { DateInput } from "@mantine/dates";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import {
  IconArrowsSort, IconPaperclip, IconPencil, IconSearch, IconSortAscending, IconSortDescending, IconTrash,
} from "@tabler/icons-react";
import dayjs from "dayjs";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "../api/client";
import { useInvalidate } from "../api/hooks";
import type { Attachment, Service } from "../api/types";
import { day, isoDate, km, money, toCents } from "../lib/format";
import { FilePicker } from "./QuickLog";
import { ServiceTypeMultiPicker } from "./ServiceTypePicker";
import { notifyError } from "./status";

type SortKey = "date" | "odometer_km" | "cost_cents";

function work(s: Service) {
  return s.type_names.join(", ") || (s.notes ? s.notes : "Service");
}

function EditService({ service, onSaved, onCancel }: {
  service: Service; onSaved: (s: Service) => void; onCancel: () => void;
}) {
  const [date, setDate] = useState<Date | null>(dayjs(service.date).toDate());
  const [odo, setOdo] = useState<number | string>(service.odometer_km ?? "");
  const [typeIds, setTypeIds] = useState<string[]>(service.items.map((i) => String(i.service_type_id)));
  const [cost, setCost] = useState<number | string>(service.cost_cents / 100);
  const [vendor, setVendor] = useState(service.vendor ?? "");
  const [notes, setNotes] = useState(service.notes ?? "");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const invalidate = useInvalidate();

  async function save() {
    setBusy(true);
    try {
      const out = await api<Service>(`/services/${service.id}`, {
        method: "PATCH",
        json: {
          date: isoDate(date), odometer_km: odo === "" ? null : Number(odo), cost_cents: toCents(cost),
          vendor, notes, type_ids: typeIds.map(Number),
        },
      });
      for (const f of files) {
        const fd = new FormData();
        fd.set("file", f);
        out.attachments.push(await api<Attachment>(`/services/${service.id}/attachments`, { method: "POST", body: fd }));
        setFiles((left) => left.filter((x) => x !== f)); // a retry after a failure won't upload it twice
      }
      await invalidate();
      onSaved(out);
      notifications.show({ color: "green", message: "Service updated" });
    } catch (e) {
      notifyError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stack>
      <ServiceTypeMultiPicker label="What was done?" value={typeIds} onChange={setTypeIds} />
      <Group grow align="flex-start">
        <DateInput label="Date" value={date} onChange={setDate} maxDate={new Date()} valueFormat="MMM D, YYYY" />
        <NumberInput label="Odometer (km)" value={odo} onChange={setOdo} thousandSeparator="," min={0} inputMode="numeric" />
      </Group>
      <Group grow align="flex-start">
        <NumberInput label="Total cost" value={cost} onChange={setCost} leftSection="$" decimalScale={2}
          fixedDecimalScale min={0} inputMode="decimal" />
        <TextInput label="Shop / vendor" value={vendor} onChange={(e) => setVendor(e.currentTarget.value)} />
      </Group>
      <Textarea label="Notes" autosize minRows={2} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
      <FilePicker files={files} setFiles={setFiles} />
      <Group justify="flex-end">
        <Button variant="default" onClick={onCancel}>Cancel</Button>
        <Button onClick={save} loading={busy} disabled={!date}>Save changes</Button>
      </Group>
    </Stack>
  );
}

export function ServiceDrawer({ service, onClose }: { service: Service | null; onClose: () => void }) {
  const mobile = useMediaQuery("(max-width: 48em)");
  const [shown, setShown] = useState<Service | null>(service);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const invalidate = useInvalidate();
  useEffect(() => {
    setShown(service);
    setEditing(false);
    setConfirmDelete(false);
  }, [service]);

  async function remove() {
    if (!shown) return;
    try {
      await api(`/services/${shown.id}`, { method: "DELETE" });
      await invalidate();
      notifications.show({ color: "green", message: "Service deleted" });
      onClose();
    } catch (e) {
      notifyError(e);
    }
  }

  async function removeFile(id: number) {
    if (!shown) return;
    try {
      await api(`/attachments/${id}`, { method: "DELETE" });
      setShown({ ...shown, attachments: shown.attachments.filter((a) => a.id !== id) });
      await invalidate();
    } catch (e) {
      notifyError(e);
    }
  }

  const s = shown;
  return (
    <Drawer opened={!!service} onClose={onClose} position={mobile ? "bottom" : "right"} size={mobile ? "85%" : "lg"}
      title={s ? `${day(s.date)} · ${work(s)}` : ""}>
      {s && editing && <EditService service={s} onCancel={() => setEditing(false)}
        onSaved={(out) => { setShown(out); setEditing(false); }} />}
      {s && !editing && (
        <ServiceDetails service={s} onRemoveFile={removeFile} actions={
          <Group gap="xs">
            <Button size="compact-sm" variant="default" leftSection={<IconPencil size={14} />}
              onClick={() => setEditing(true)}>Edit</Button>
            {confirmDelete ? (
              <>
                <Button size="compact-sm" color="red" onClick={remove}>Delete, including receipts</Button>
                <Button size="compact-sm" variant="subtle" onClick={() => setConfirmDelete(false)}>Keep</Button>
              </>
            ) : (
              <Button size="compact-sm" variant="subtle" color="red" leftSection={<IconTrash size={14} />}
                onClick={() => setConfirmDelete(true)}>Delete</Button>
            )}
          </Group>
        } />
      )}
    </Drawer>
  );
}

function ServiceDetails({ service, actions, onRemoveFile }: {
  service: Service; actions: ReactNode; onRemoveFile: (id: number) => void;
}) {
  return (
        <Stack>
          {actions}
          <Group gap="xl">
            <div><Text size="xs" c="dimmed">Odometer</Text><Text>{km(service.odometer_km)}</Text></div>
            <div><Text size="xs" c="dimmed">Cost</Text><Text>{money(service.cost_cents)}</Text></div>
            <div><Text size="xs" c="dimmed">Vendor</Text><Text>{service.vendor ?? "—"}</Text></div>
          </Group>
          {service.notes && <Text>{service.notes}</Text>}
          {service.attachments.length === 0 && <Text c="dimmed">No receipts attached.</Text>}
          {service.attachments.map((a) => (
            <Stack key={a.id} gap={4}>
              <Group justify="space-between">
                <Text size="sm">{a.orig_name}</Text>
                <Group gap="sm">
                  <Anchor size="sm" href={`/api/v1/attachments/${a.id}?download=true`}>Download</Anchor>
                  <Anchor size="sm" c="red" component="button" onClick={() => onRemoveFile(a.id)}>Remove</Anchor>
                </Group>
              </Group>
              {a.mime.startsWith("image/") && a.mime !== "image/heic" ? (
                <Image src={`/api/v1/attachments/${a.id}`} alt={a.orig_name} radius="sm" />
              ) : a.mime === "application/pdf" ? (
                <iframe title={a.orig_name} src={`/api/v1/attachments/${a.id}`}
                  style={{ width: "100%", height: 480, border: 0 }} />
              ) : (
                <Text size="sm" c="dimmed">No preview for this file type. Use Download.</Text>
              )}
            </Stack>
          ))}
        </Stack>
  );
}

function SortHead({ label, k, sort, setSort, right }: {
  label: string; k: SortKey; sort: { k: SortKey; dir: 1 | -1 }; setSort: (s: { k: SortKey; dir: 1 | -1 }) => void;
  right?: boolean;
}) {
  const Icon = sort.k !== k ? IconArrowsSort : sort.dir === 1 ? IconSortAscending : IconSortDescending;
  return (
    <Table.Th ta={right ? "right" : undefined}>
      <UnstyledButton onClick={() => setSort({ k, dir: sort.k === k ? (sort.dir === 1 ? -1 : 1) : -1 })}>
        <Group gap={4} wrap="nowrap">{label}<Icon size={14} /></Group>
      </UnstyledButton>
    </Table.Th>
  );
}

/** Sortable/filterable table on desktop, stacked cards on phones. */
export function ServicesList({ services, filterable = true }: { services: Service[]; filterable?: boolean }) {
  const [open, setOpen] = useState<Service | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ k: SortKey; dir: 1 | -1 }>({ k: "date", dir: -1 });
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return services
      .filter((s) => !needle || `${work(s)} ${s.vendor ?? ""} ${s.notes ?? ""}`.toLowerCase().includes(needle))
      .sort((a, b) => {
        const av = a[sort.k] ?? -1, bv = b[sort.k] ?? -1;
        return (av < bv ? -1 : av > bv ? 1 : 0) * sort.dir;
      });
  }, [services, q, sort]);

  if (!services.length) return <Text c="dimmed">No services logged yet. Use Quick log to add the first one.</Text>;

  return (
    <Stack>
      {filterable && (
        <TextInput placeholder="Filter by work, vendor or notes" leftSection={<IconSearch size={16} />}
          value={q} onChange={(e) => setQ(e.currentTarget.value)} maw={360} />
      )}
      <Table.ScrollContainer minWidth={0} visibleFrom="sm">
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <SortHead label="Date" k="date" sort={sort} setSort={setSort} />
              <Table.Th>Work</Table.Th>
              <SortHead label="Odometer" k="odometer_km" sort={sort} setSort={setSort} right />
              <SortHead label="Cost" k="cost_cents" sort={sort} setSort={setSort} right />
              <Table.Th aria-label="Receipts" />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((s) => (
              <Table.Tr key={s.id} onClick={() => setOpen(s)} style={{ cursor: "pointer" }}>
                <Table.Td>{day(s.date)}</Table.Td>
                <Table.Td>{work(s)}{s.vendor && <Text span c="dimmed"> · {s.vendor}</Text>}</Table.Td>
                <Table.Td ta="right">{km(s.odometer_km)}</Table.Td>
                <Table.Td ta="right">{money(s.cost_cents)}</Table.Td>
                <Table.Td>{s.attachments.length > 0 && <Badge variant="light" leftSection={<IconPaperclip size={12} />}>{s.attachments.length}</Badge>}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Stack gap="xs" hiddenFrom="sm">
        {rows.map((s) => (
          <Card key={s.id} withBorder padding="sm" onClick={() => setOpen(s)} style={{ cursor: "pointer" }}>
            <Group justify="space-between" wrap="nowrap">
              <Text fw={600}>{work(s)}</Text>
              <Text>{money(s.cost_cents)}</Text>
            </Group>
            <Group justify="space-between">
              <Text size="sm" c="dimmed">{day(s.date)} · {km(s.odometer_km)}{s.vendor ? ` · ${s.vendor}` : ""}</Text>
              {s.attachments.length > 0 && <IconPaperclip size={16} />}
            </Group>
          </Card>
        ))}
      </Stack>
      <ServiceDrawer service={open} onClose={() => setOpen(null)} />
    </Stack>
  );
}
