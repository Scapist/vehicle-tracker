import {
  Anchor, Badge, Button, Card, Checkbox, Group, Loader, Modal, NumberInput, Select, SimpleGrid, Stack, Switch,
  Table, Tabs, Text, TextInput, Title,
} from "@mantine/core";
import { DateInput } from "@mantine/dates";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { IconPlus, IconPrinter } from "@tabler/icons-react";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import {
  useApiMutation, useDashboard, useDateItems, useOdometer, useRules, useServices, useServiceTypes,
} from "../api/hooks";
import type { Rule, ServiceType, Vehicle } from "../api/types";
import { useUser } from "../components/AuthGate";
import { ItemCard } from "../components/ItemCard";
import { PaymentsTab } from "../components/PaymentsTab";
import { useQuickLog } from "../components/QuickLog";
import { ServicesList } from "../components/ServicesList";
import { ServiceTypeSelect } from "../components/ServiceTypePicker";
import { notifyError, notifyUndo } from "../components/status";
import { day, isoDate, km, money } from "../lib/format";

export default function VehiclePage() {
  const id = Number(useParams().id);
  const dash = useDashboard(id);
  const quick = useQuickLog();
  const services = useServices(id);
  const [params, setParams] = useSearchParams(); // ?tab=payments etc., so other pages can link to a tab
  const tab = params.get("tab") ?? "overview";
  if (dash.isLoading) return <Loader />;
  if (dash.error || !dash.data) return <Text c="red">Couldn't load that vehicle.</Text>;
  const { vehicle: v, items } = dash.data;
  const attention = items.filter((i) => ["overdue", "due_soon", "unknown"].includes(i.status) && !i.informational);
  const upcoming = items.filter((i) => !attention.includes(i));

  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>{v.nickname}</Title>
          <Text c="dimmed">
            {v.year} {v.make} {v.model} · {km(v.current_km)}
            {dash.data.km_per_day ? ` · about ${Math.round(dash.data.km_per_day)} km/day` : ""}
          </Text>
        </div>
        <Group gap="xs">
          <Button variant="light" onClick={() => quick.open("mileage", id)}>Update km</Button>
          <Button onClick={() => quick.open("service", id)}>Log service</Button>
        </Group>
      </Group>

      <Tabs value={tab} onChange={(t) => setParams(t && t !== "overview" ? { tab: t } : {}, { replace: true })}
        keepMounted={false}>
        <Tabs.List style={{ flexWrap: "nowrap", overflowX: "auto", overflowY: "hidden" }}>
          <Tabs.Tab value="overview">Overview</Tabs.Tab>
          <Tabs.Tab value="services">Services</Tabs.Tab>
          <Tabs.Tab value="odometer">Odometer</Tabs.Tab>
          <Tabs.Tab value="reminders">Reminders</Tabs.Tab>
          <Tabs.Tab value="payments">Payments</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="overview" pt="md">
          <Stack>
            <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
              <Stack>
                <Title order={4}>Needs attention</Title>
                {attention.length === 0 && <Text c="dimmed">Nothing needs attention. 🎉</Text>}
                {attention.map((i) => <ItemCard key={i.subject} item={i} />)}
              </Stack>
              <Stack>
                <Title order={4}>Upcoming</Title>
                {upcoming.length === 0 && (
                  <Text c="dimmed">No reminders set. Add some under “Reminders &amp; dates”.</Text>
                )}
                {upcoming.map((i) => <ItemCard key={i.subject} item={i} />)}
              </Stack>
            </SimpleGrid>
            <Group justify="space-between" mt="md">
              <Title order={4}>Recent services</Title>
              <Text c="dimmed">{dash.data.year}: {money(dash.data.year_cost_cents)}</Text>
            </Group>
            <ServicesList services={dash.data.recent_services} filterable={false} />
            {dash.data.mounted_tire_set && (
              <Text size="sm" c="dimmed">
                Tires on the car: {dash.data.mounted_tire_set.label} · {km(dash.data.mounted_tire_set.total_km)}
              </Text>
            )}
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="services" pt="md">
          <Stack>
            <Anchor component={Link} to={`/vehicles/${id}/history`} size="sm">
              <Group gap={4}><IconPrinter size={14} />Printable service history</Group>
            </Anchor>
            <ServicesList services={services.data ?? []} />
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="odometer" pt="md"><OdometerTab id={id} vehicle={v} /></Tabs.Panel>
        <Tabs.Panel value="reminders" pt="md"><RemindersTab id={id} /></Tabs.Panel>
        <Tabs.Panel value="payments" pt="md"><PaymentsTab vehicleId={id} /></Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

const NUDGE = [
  { value: "7", label: "After a week" }, { value: "14", label: "After 2 weeks" },
  { value: "30", label: "After a month" }, { value: "0", label: "Never" },
];

function NudgeSetting({ vehicle }: { vehicle: Vehicle }) {
  const user = useUser();
  const save = useApiMutation((days: number) => api(`/vehicles/${vehicle.id}`, { method: "PATCH", json: { nudge_days: days } }));
  const value = String(vehicle.nudge_days);
  const data = NUDGE.some((n) => n.value === value) ? NUDGE : [...NUDGE, { value, label: `After ${value} days` }];
  return (
    <Card withBorder padding="sm">
      <Group justify="space-between" align="flex-end" wrap="wrap" gap="xs">
        <div style={{ flex: "1 1 240px" }}>
          <Text fw={600} size="sm">Ask me for the km on Telegram</Text>
          <Text size="xs" c="dimmed">
            {user.telegram_linked
              ? "When there's been no new reading for this long. Km reminders are only as accurate as the latest reading."
              : "Connect Telegram in Settings first: that's where the question is sent."}
          </Text>
        </div>
        <Select aria-label="Ask me for the km" w={160} allowDeselect={false} data={data} value={value}
          onChange={(v) => v && save.mutate(Number(v), { onError: notifyError })} />
      </Group>
    </Card>
  );
}

function OdometerTab({ id, vehicle }: { id: number; vehicle: Vehicle }) {
  const odo = useOdometer(id);
  if (!odo.data?.length) {
    return (
      <Stack>
        <NudgeSetting vehicle={vehicle} />
        <Text c="dimmed">No readings yet. Use Update km to add the first one.</Text>
      </Stack>
    );
  }
  return (
    <Stack>
      <NudgeSetting vehicle={vehicle} />
      <Table.ScrollContainer minWidth={0}>
        <Table>
          <Table.Thead>
            <Table.Tr><Table.Th>Date</Table.Th><Table.Th ta="right">Odometer</Table.Th><Table.Th>Source</Table.Th></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {odo.data.map((r) => (
              <Table.Tr key={r.id} c={r.invalidated ? "dimmed" : undefined}>
                <Table.Td>{day(r.recorded_at)}</Table.Td>
                <Table.Td ta="right" td={r.invalidated ? "line-through" : undefined}>{km(r.km)}</Table.Td>
                <Table.Td>
                  {r.source}
                  {r.is_correction && <Badge ml="xs" color="orange" variant="light">correction</Badge>}
                  {r.invalidated && <Badge ml="xs" color="gray" variant="light">replaced</Badge>}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
}

function RemindersTab({ id }: { id: number }) {
  const rules = useRules(id);
  const types = useServiceTypes();
  const dates = useDateItems(id);
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const [addingDate, dateModal] = useDisclosure(false);
  const typeName = (tid: number) => types.data?.find((t) => t.id === tid)?.name ?? "Service";
  const patch = useApiMutation((a: { id: number; body: object }) => api(`/rules/${a.id}`, { method: "PATCH", json: a.body }));
  const addDate = useApiMutation((b: object) => api("/date-items", { method: "POST", json: b }));

  async function addWinter() {
    const y = new Date().getFullYear();
    const dec = new Date(y, 11, 1) < new Date() ? y + 1 : y;
    try {
      await addDate.mutateAsync({ vehicle_id: id, kind: "winter_install", title: "Install winter tires by Dec 1",
        due_date: `${dec}-12-01`, recurs_yearly: true, soon_days: 30 });
      await addDate.mutateAsync({ vehicle_id: id, kind: "winter_remove", title: "Winter tires can come off after Mar 15",
        due_date: `${dec + 1}-03-15`, recurs_yearly: true, soon_days: 14, informational: true });
    } catch (e) {
      notifyError(e);
    }
  }

  return (
    <Stack gap="xl">
      <Stack>
        <Group justify="space-between">
          <Title order={4}>Maintenance reminders</Title>
          <Button size="compact-md" leftSection={<IconPlus size={14} />} onClick={() => setEditing("new")}>Add reminder</Button>
        </Group>
        {rules.data?.length === 0 && <Text c="dimmed">No reminders yet. Add one, e.g. oil change every 8,000 km or 6 months.</Text>}
        {rules.data?.map((r) => (
          <Card key={r.id} withBorder padding="sm">
            <Group justify="space-between" wrap="nowrap">
              <div>
                <Text fw={600}>{typeName(r.service_type_id)}</Text>
                <Text size="sm" c="dimmed">
                  Every {[r.interval_km && km(r.interval_km), r.interval_months && `${r.interval_months} months`].filter(Boolean).join(" or ")}
                  {" · "}warn {[r.soon_km ? km(r.soon_km) : null, r.soon_days ? `${r.soon_days} days` : null].filter(Boolean).join(" / ")} ahead
                </Text>
              </div>
              <Group gap="xs" wrap="nowrap">
                <Switch checked={r.enabled} aria-label="Enabled"
                  onChange={(e) => patch.mutate({ id: r.id, body: { enabled: e.currentTarget.checked } }, { onError: notifyError })} />
                <Button size="compact-sm" variant="default" onClick={() => setEditing(r)}>Edit</Button>
              </Group>
            </Group>
          </Card>
        ))}
      </Stack>

      <Stack>
        <Group justify="space-between">
          <Title order={4}>Dates</Title>
          <Group gap="xs">
            <Button size="compact-md" variant="default" onClick={addWinter}>Add winter-tire reminders</Button>
            <Button size="compact-md" leftSection={<IconPlus size={14} />} onClick={dateModal.open}>Add date</Button>
          </Group>
        </Group>
        {dates.data?.length === 0 && <Text c="dimmed">No dates yet: registration, insurance, winter tires…</Text>}
        {dates.data?.map((d) => (
          <Card key={d.id} withBorder padding="sm">
            <Group justify="space-between">
              <div>
                <Text fw={600}>{d.title}</Text>
                <Text size="sm" c="dimmed">{day(d.due_date)}{d.recurs_yearly ? " · repeats yearly" : ""}</Text>
              </div>
              <Button size="compact-sm" variant="subtle" color="red" onClick={async () => {
                try {
                  await api(`/date-items/${d.id}`, { method: "DELETE" });
                  notifyUndo(`Removed “${d.title}”`, async () => {
                    await api("/date-items", { method: "POST", json: { vehicle_id: id, kind: d.kind, title: d.title,
                      due_date: d.due_date, recurs_yearly: d.recurs_yearly, soon_days: d.soon_days, informational: d.informational } });
                  });
                  dates.refetch();
                } catch (e) { notifyError(e); }
              }}>Remove</Button>
            </Group>
          </Card>
        ))}
      </Stack>

      {editing && (
        <RuleModal vehicleId={id} rule={editing === "new" ? null : editing} types={types.data ?? []}
          existing={rules.data ?? []} onClose={() => setEditing(null)} />
      )}
      <DateModal vehicleId={id} opened={addingDate} onClose={dateModal.close} />
    </Stack>
  );
}

function RuleModal({ vehicleId, rule, types, existing, onClose }: {
  vehicleId: number; rule: Rule | null; types: ServiceType[]; existing: Rule[]; onClose: () => void;
}) {
  const mobile = useMediaQuery("(max-width: 48em)");
  const available = (t: ServiceType) => !existing.some((r) => r.service_type_id === t.id) || t.id === rule?.service_type_id;
  const [typeId, setTypeId] = useState<string | null>(rule ? String(rule.service_type_id) : null);
  const [ikm, setIkm] = useState<number | string>(rule?.interval_km ?? "");
  const [imo, setImo] = useState<number | string>(rule?.interval_months ?? "");
  const [skm, setSkm] = useState<number | string>(rule?.soon_km ?? 1000);
  const [sd, setSd] = useState<number | string>(rule?.soon_days ?? 30);
  const [bdate, setBdate] = useState<Date | null>(rule?.baseline_date ? dayjs(rule.baseline_date).toDate() : null);
  const [bkm, setBkm] = useState<number | string>(rule?.baseline_km ?? "");
  const save = useApiMutation((b: object) => rule
    ? api(`/rules/${rule.id}`, { method: "PATCH", json: b })
    : api(`/vehicles/${vehicleId}/rules`, { method: "POST", json: b }));

  function pickType(v: string | null) {
    setTypeId(v);
    const t = types.find((x) => String(x.id) === v);
    if (t && !rule) { // prefill from the service type's defaults
      setIkm(t.default_interval_km ?? ""); setImo(t.default_interval_months ?? "");
      setSkm(t.default_soon_km); setSd(t.default_soon_days);
    }
  }
  const num = (v: number | string) => (v === "" ? null : Number(v));

  async function submit() {
    try {
      await save.mutateAsync({
        ...(rule ? {} : { service_type_id: Number(typeId) }),
        interval_km: num(ikm), interval_months: num(imo), soon_km: Number(skm || 0), soon_days: Number(sd || 0),
        baseline_date: bdate ? isoDate(bdate) : null, baseline_km: num(bkm),
      });
      onClose();
    } catch (e) { notifyError(e); }
  }

  return (
    <Modal opened onClose={onClose} title={rule ? "Edit reminder" : "Add reminder"} fullScreen={!!mobile}>
      <Stack>
        {!rule && <ServiceTypeSelect label="Service" include={available} value={typeId} onChange={pickType} />}
        <Group grow align="flex-start">
          <NumberInput label="Every (km)" value={ikm} onChange={setIkm} thousandSeparator="," min={1} />
          <NumberInput label="Every (months)" value={imo} onChange={setImo} min={1} />
        </Group>
        <Text size="xs" c="dimmed">Set either or both. With both, whichever comes first counts.</Text>
        <Group grow align="flex-start">
          <NumberInput label="Warn at (km before)" value={skm} onChange={setSkm} thousandSeparator="," min={0} />
          <NumberInput label="Warn at (days before)" value={sd} onChange={setSd} min={0} />
        </Group>
        <Text size="sm" fw={500}>When was this last done? (used until you log a service)</Text>
        <Group grow align="flex-start">
          <DateInput label="Date" value={bdate} onChange={setBdate} clearable maxDate={new Date()} />
          <NumberInput label="Odometer (km)" value={bkm} onChange={setBkm} thousandSeparator="," min={0} />
        </Group>
        <Button onClick={submit} loading={save.isPending} disabled={!rule && !typeId || (ikm === "" && imo === "")}>Save</Button>
      </Stack>
    </Modal>
  );
}

function DateModal({ vehicleId, opened, onClose }: { vehicleId: number; opened: boolean; onClose: () => void }) {
  const mobile = useMediaQuery("(max-width: 48em)");
  const [kind, setKind] = useState<string>("registration");
  const [title, setTitle] = useState("");
  const [due, setDue] = useState<Date | null>(null);
  const [yearly, setYearly] = useState(true);
  const [soon, setSoon] = useState<number | string>(30);
  const create = useApiMutation((b: object) => api("/date-items", { method: "POST", json: b }));
  const labels: Record<string, string> = { registration: "Registration renewal", insurance: "Insurance renewal", custom: "" };
  async function submit() {
    try {
      await create.mutateAsync({ vehicle_id: vehicleId, kind, title: title || labels[kind], due_date: isoDate(due),
        recurs_yearly: yearly, soon_days: Number(soon || 0) });
      onClose();
    } catch (e) { notifyError(e); }
  }
  return (
    <Modal opened={opened} onClose={onClose} title="Add date" fullScreen={!!mobile}>
      <Stack>
        <Select label="Type" value={kind} onChange={(v) => v && setKind(v)} allowDeselect={false}
          data={[{ value: "registration", label: "Registration" }, { value: "insurance", label: "Insurance" }, { value: "custom", label: "Other" }]} />
        <TextInput label="Title" placeholder={labels[kind] || "e.g. Emissions test"} value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
        <DateInput label="Due date" value={due} onChange={setDue} />
        <NumberInput label="Warn this many days ahead" value={soon} onChange={setSoon} min={0} />
        <Checkbox label="Repeats every year" checked={yearly} onChange={(e) => setYearly(e.currentTarget.checked)} />
        <Button onClick={submit} loading={create.isPending} disabled={!due || (kind === "custom" && !title)}>Add</Button>
      </Stack>
    </Modal>
  );
}
