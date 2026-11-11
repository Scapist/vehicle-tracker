import {
  Anchor, Badge, Card, Drawer, Group, Image, Stack, Table, Text, TextInput, UnstyledButton,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconArrowsSort, IconPaperclip, IconSearch, IconSortAscending, IconSortDescending } from "@tabler/icons-react";
import { useMemo, useState } from "react";

import type { Service } from "../api/types";
import { day, km, money } from "../lib/format";

type SortKey = "date" | "odometer_km" | "cost_cents";

function work(s: Service) {
  return s.type_names.join(", ") || (s.notes ? s.notes : "Service");
}

export function ServiceDrawer({ service, onClose }: { service: Service | null; onClose: () => void }) {
  const mobile = useMediaQuery("(max-width: 48em)");
  return (
    <Drawer opened={!!service} onClose={onClose} position={mobile ? "bottom" : "right"} size={mobile ? "85%" : "lg"}
      title={service ? `${day(service.date)} · ${work(service)}` : ""}>
      {service && (
        <Stack>
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
                <Anchor size="sm" href={`/api/v1/attachments/${a.id}?download=true`}>Download</Anchor>
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
      )}
    </Drawer>
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
