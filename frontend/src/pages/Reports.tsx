import { BarChart } from "@mantine/charts";
import { Anchor, Card, Group, Select, Stack, Table, Text, Title } from "@mantine/core";
import { IconDownload } from "@tabler/icons-react";
import { useState } from "react";

import { useReport, useVehicles } from "../api/hooks";
import { km, money } from "../lib/format";

const COLORS = ["blue.6", "teal.6", "orange.6", "grape.6", "red.6", "cyan.6", "lime.6", "pink.6", "yellow.6", "gray.6"];

export default function Reports() {
  const vehicles = useVehicles();
  const [vid, setVid] = useState<string>("all");
  const report = useReport(vid === "all" ? undefined : Number(vid));
  const data = report.data;
  const chart = (data?.years ?? []).map((y) => ({ year: String(y.year), ...Object.fromEntries(Object.entries(y.by_category).map(([k, v]) => [k, v / 100])) }));
  const q = vid === "all" ? "" : `?vehicle=${vid}`;
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Reports</Title>
        <Select aria-label="Vehicle" w={180} allowDeselect={false} value={vid} onChange={(v) => v && setVid(v)}
          data={[{ value: "all", label: "All vehicles" }, ...(vehicles.data ?? []).map((v) => ({ value: String(v.id), label: v.nickname }))]} />
      </Group>
      {data && data.years.length === 0 && <Text c="dimmed">Nothing to report yet. Log a service or some mileage first.</Text>}
      {data && data.years.length > 0 && (
        <>
          <Title order={4}>Cost per year</Title>
          <BarChart h={280} data={chart} dataKey="year" type="stacked" withLegend
            valueFormatter={(v) => v.toLocaleString("en-CA", { style: "currency", currency: "CAD" })}
            series={data.categories.map((c, i) => ({ name: c, color: COLORS[i % COLORS.length] }))} />
          <Table.ScrollContainer minWidth={0} visibleFrom="sm">
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Year</Table.Th>
                  {data.categories.map((c) => <Table.Th key={c} ta="right">{c}</Table.Th>)}
                  <Table.Th ta="right">Total</Table.Th>
                  <Table.Th ta="right">Driven</Table.Th>
                  <Table.Th ta="right">Cost / km</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.years.map((y) => (
                  <Table.Tr key={y.year}>
                    <Table.Td>{y.year}</Table.Td>
                    {data.categories.map((c) => <Table.Td key={c} ta="right">{y.by_category[c] ? money(y.by_category[c]) : "—"}</Table.Td>)}
                    <Table.Td ta="right" fw={700}>{money(y.total_cents)}</Table.Td>
                    <Table.Td ta="right">{y.km ? km(y.km) : "—"}</Table.Td>
                    <Table.Td ta="right">{y.cost_per_km_cents != null ? `${y.cost_per_km_cents.toFixed(1)}¢` : "—"}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Stack gap="xs" hiddenFrom="sm">
            {[...data.years].reverse().map((y) => (
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
          <Anchor key={n} href={`/api/v1/export/${n}.csv${q}`} download>
            <Group gap={4}><IconDownload size={14} />{n}.csv</Group>
          </Anchor>
        ))}
      </Group>
    </Stack>
  );
}
