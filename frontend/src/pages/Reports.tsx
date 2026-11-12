import { BarChart } from "@mantine/charts";
import {
  Anchor, Badge, Button, Card, Group, MultiSelect, Progress, Select, SimpleGrid, Stack, Table, Text, Title,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useMediaQuery } from "@mantine/hooks";
import { IconDownload } from "@tabler/icons-react";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { spendingQuery, useReport, useSpending, useVehicles } from "../api/hooks";
import { api } from "../api/client";
import type { Service, SpendingEntry } from "../api/types";
import { ServiceDrawer } from "../components/ServicesList";
import { notifyError } from "../components/status";
import { day, km, money } from "../lib/format";

const COLORS = ["blue.6", "teal.6", "orange.6", "grape.6", "red.6", "cyan.6", "lime.6", "pink.6", "yellow.6", "gray.6"];
const FMT = "YYYY-MM-DD";

const PERIODS: Record<string, { label: string; range?: () => [dayjs.Dayjs, dayjs.Dayjs] }> = {
  "this-month": { label: "This month", range: () => [dayjs().startOf("month"), dayjs().endOf("month")] },
  "last-month": {
    label: "Last month",
    range: () => [dayjs().subtract(1, "month").startOf("month"), dayjs().subtract(1, "month").endOf("month")],
  },
  "this-year": { label: "This year", range: () => [dayjs().startOf("year"), dayjs().endOf("year")] },
  "last-year": {
    label: "Last year",
    range: () => [dayjs().subtract(1, "year").startOf("year"), dayjs().subtract(1, "year").endOf("year")],
  },
  "12-months": { label: "Last 12 months", range: () => [dayjs().subtract(11, "month").startOf("month"), dayjs().endOf("month")] },
  custom: { label: "Custom range" },
};

export default function Reports() {
  // filters live in the URL, so a view can be bookmarked or shared between your devices
  const [params, setParams] = useSearchParams();
  const period = PERIODS[params.get("period") ?? ""] ? params.get("period")! : "this-year";
  const vid = params.get("vehicle") ?? "all";
  const categories = params.getAll("category");
  const preset = PERIODS[period].range?.();
  const from = preset ? preset[0].format(FMT) : params.get("from") ?? dayjs().startOf("year").format(FMT);
  const to = preset ? preset[1].format(FMT) : params.get("to") ?? dayjs().endOf("year").format(FMT);

  function update(changes: Record<string, string | string[] | null>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      next.delete(k);
      if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
      else if (v != null) next.set(k, v);
    }
    setParams(next, { replace: true });
  }

  const vehicles = useVehicles();
  const names = Object.fromEntries((vehicles.data ?? []).map((v) => [v.id, v.nickname]));
  const filter = { from, to, vehicle: vid === "all" ? undefined : Number(vid), categories };
  const spending = useSpending(filter);
  const s = spending.data;
  const report = useReport(filter.vehicle);
  const years = report.data;

  const thisMonth = dayjs().format("YYYY-MM");
  const elapsed = Math.max(1, (s?.by_month ?? []).filter((m) => m.month <= thisMonth).length);
  const monthCats = [...new Set((s?.by_month ?? []).flatMap((m) => Object.keys(m.by_category)))].sort();
  const chart = (s?.by_month ?? []).map((m) => ({
    month: dayjs(`${m.month}-01`).format("MMM YY"),
    ...Object.fromEntries(Object.entries(m.by_category).map(([k, v]) => [k, v / 100])),
  }));

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Reports</Title>
        <Anchor href={`/api/v1/export/spending.csv?${spendingQuery(filter)}`} download size="sm">
          <Group gap={4}><IconDownload size={14} />spending.csv</Group>
        </Anchor>
      </Group>

      <Group gap="sm" align="flex-end">
        <Select label="Period" w={170} allowDeselect={false} value={period}
          data={Object.entries(PERIODS).map(([value, p]) => ({ value, label: p.label }))}
          onChange={(v) => v && update(v === "custom" ? { period: v, from, to } : { period: v, from: null, to: null })} />
        {period === "custom" && (
          <DatePickerInput type="range" label="Dates" w={250} allowSingleDateInRange
            value={[dayjs(from).toDate(), dayjs(to).toDate()]}
            onChange={([a, b]) => a && b && update({ from: dayjs(a).format(FMT), to: dayjs(b).format(FMT) })} />
        )}
        <Select label="Vehicle" w={170} allowDeselect={false} value={vid}
          onChange={(v) => v && update({ vehicle: v === "all" ? null : v })}
          data={[{ value: "all", label: "All vehicles" }, ...(vehicles.data ?? []).map((v) => ({ value: String(v.id), label: v.nickname }))]} />
        <MultiSelect label="Categories" placeholder={categories.length ? undefined : "All categories"} clearable
          miw={200} style={{ flex: 1 }} value={categories} onChange={(v) => update({ category: v })}
          data={[...new Set([...(s?.categories ?? []), ...categories])]} />
      </Group>

      {s && (
        <>
          <Text size="sm" c="dimmed" mb={-8}>{day(from)} – {day(to)}</Text>
          <SimpleGrid cols={3} spacing="xs">
            <Stat label="Spent" value={money(s.total_cents)} />
            <Stat label="Scheduled" hint="Recurring payments still to come in this period" value={money(s.scheduled_cents)} />
            <Stat label="Per month" hint="Average over the months so far" value={money(Math.round(s.total_cents / elapsed))} />
          </SimpleGrid>

          {s.total_cents === 0 && s.scheduled_cents === 0 ? (
            <Text c="dimmed">Nothing spent in this period. Log a service, or add recurring payments on a vehicle's Payments tab.</Text>
          ) : (
            <>
              <Title order={4}>Month by month</Title>
              <BarChart h={260} data={chart} dataKey="month" type="stacked" withLegend
                valueFormatter={(v) => v.toLocaleString("en-CA", { style: "currency", currency: "CAD" })}
                series={monthCats.map((c, i) => ({ name: c, color: COLORS[i % COLORS.length] }))} />

              <Title order={4}>By category</Title>
              <Stack gap="xs">
                {Object.entries(s.by_category).map(([c, v]) => (
                  <div key={c}>
                    <Group justify="space-between">
                      <Text size="sm">{c}</Text>
                      <Text size="sm" fw={600}>{money(v)} <Text span c="dimmed" size="sm">
                        ({Math.round((v / s.total_cents) * 100)}%)</Text></Text>
                    </Group>
                    <Progress value={(v / s.total_cents) * 100} size="sm" aria-label={`${c} share`} />
                  </div>
                ))}
              </Stack>

              <Entries entries={s.entries} names={names} />
            </>
          )}
        </>
      )}

      {years && years.years.length > 0 && (
        <>
          <Title order={4} mt="md">By year</Title>
          <Table.ScrollContainer minWidth={0} visibleFrom="sm">
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Year</Table.Th>
                  {years.categories.map((c) => <Table.Th key={c} ta="right">{c}</Table.Th>)}
                  <Table.Th ta="right">Total</Table.Th>
                  <Table.Th ta="right">Driven</Table.Th>
                  <Table.Th ta="right">Cost / km</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {years.years.map((y) => (
                  <Table.Tr key={y.year}>
                    <Table.Td>{y.year}</Table.Td>
                    {years.categories.map((c) => <Table.Td key={c} ta="right">{y.by_category[c] ? money(y.by_category[c]) : "—"}</Table.Td>)}
                    <Table.Td ta="right" fw={700}>{money(y.total_cents)}</Table.Td>
                    <Table.Td ta="right">{y.km ? km(y.km) : "—"}</Table.Td>
                    <Table.Td ta="right">{y.cost_per_km_cents != null ? `${y.cost_per_km_cents.toFixed(1)}¢` : "—"}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Stack gap="xs" hiddenFrom="sm">
            {[...years.years].reverse().map((y) => (
              <Card key={y.year} withBorder padding="sm">
                <Group justify="space-between">
                  <Text fw={700}>{y.year}</Text>
                  <Text fw={700}>{money(y.total_cents)}</Text>
                </Group>
                <Text size="sm" c="dimmed">
                  {y.km ? `${km(y.km)} driven` : "No mileage data"}
                  {y.cost_per_km_cents != null ? ` · ${y.cost_per_km_cents.toFixed(1)}¢/km` : ""}
                </Text>
                {Object.entries(y.by_category).map(([c, v]) => (
                  <Group key={c} justify="space-between" mt={4}>
                    <Text size="sm">{c}</Text>
                    <Text size="sm">{money(v)}</Text>
                  </Group>
                ))}
              </Card>
            ))}
          </Stack>
        </>
      )}

      <Group gap="lg">
        {["services", "odometer", "tires"].map((n) => (
          <Anchor key={n} href={`/api/v1/export/${n}.csv${vid === "all" ? "" : `?vehicle=${vid}`}`} download size="sm">
            <Group gap={4}><IconDownload size={14} />{n}.csv</Group>
          </Anchor>
        ))}
      </Group>
    </Stack>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  const mobile = useMediaQuery("(max-width: 48em)");
  return (
    <Card withBorder padding={mobile ? "xs" : "sm"} title={hint}>
      <Text size="xs" c="dimmed">{label}</Text>
      <Text fw={700} size={mobile ? "sm" : "xl"} style={{ whiteSpace: "nowrap" }}>{value}</Text>
    </Card>
  );
}

const PAGE = 25;

function Entries({ entries, names }: { entries: SpendingEntry[]; names: Record<number, string> }) {
  const [shown, setShown] = useState(PAGE);
  const [service, setService] = useState<Service | null>(null);
  const navigate = useNavigate();
  const list = entries.slice(0, shown);
  // each entry opens where it came from: the service's details, the vehicle's payments, or the tires page
  async function open(e: SpendingEntry) {
    if (e.source === "recurring") return navigate(`/vehicles/${e.vehicle_id}?tab=payments`);
    if (e.source === "tire") return navigate("/tires");
    try {
      setService(await api<Service>(`/services/${e.ref_id}`));
    } catch (err) { notifyError(err); }
  }
  const clickable = { cursor: "pointer" } as const;
  const stop = (ev: { stopPropagation: () => void }) => ev.stopPropagation(); // the vehicle link goes to the vehicle
  const scheduled = (e: SpendingEntry) => e.scheduled && <Badge size="xs" variant="light" color="gray">scheduled</Badge>;
  const vehicle = (e: SpendingEntry) => (
    <Anchor component={Link} to={`/vehicles/${e.vehicle_id}`} size="sm" onClick={stop}>{names[e.vehicle_id] ?? "—"}</Anchor>
  );
  return (
    <>
      <Title order={4}>Entries</Title>
      <Table.ScrollContainer minWidth={0} visibleFrom="sm">
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Date</Table.Th><Table.Th>Vehicle</Table.Th><Table.Th>Category</Table.Th>
              <Table.Th>What</Table.Th><Table.Th ta="right">Amount</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {list.map((e, i) => (
              <Table.Tr key={`${e.source}-${e.ref_id}-${e.date}-${e.category}-${i}`} c={e.scheduled ? "dimmed" : undefined}
                style={clickable} onClick={() => open(e)}>
                <Table.Td>{day(e.date)}</Table.Td>
                <Table.Td>{vehicle(e)}</Table.Td>
                <Table.Td>{e.category}</Table.Td>
                <Table.Td><Group gap={6}>{e.label}{scheduled(e)}</Group></Table.Td>
                <Table.Td ta="right">{money(e.cents)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Stack gap="xs" hiddenFrom="sm">
        {list.map((e, i) => (
          <Card key={`${e.source}-${e.ref_id}-${e.date}-${e.category}-${i}`} withBorder padding="sm" c={e.scheduled ? "dimmed" : undefined}
            role="button" tabIndex={0} onClick={() => open(e)} onKeyDown={(k) => k.key === "Enter" && open(e)}
            style={clickable}>
            <Group justify="space-between" wrap="nowrap">
              <Text fw={600} size="sm">{e.label}</Text>
              <Text fw={700} size="sm">{money(e.cents)}</Text>
            </Group>
            <Group gap={6}>
              <Text size="xs" c="dimmed">{day(e.date)} · {e.category} ·</Text>{vehicle(e)}{scheduled(e)}
            </Group>
          </Card>
        ))}
      </Stack>
      <ServiceDrawer service={service} onClose={() => setService(null)} />
      {entries.length > shown && (
        <Button variant="default" onClick={() => setShown((n) => n + PAGE)}>Show more ({entries.length - shown} left)</Button>
      )}
    </>
  );
}
