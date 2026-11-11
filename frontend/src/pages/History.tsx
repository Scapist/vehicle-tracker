import { Button, Group, Loader, Table, Text, Title } from "@mantine/core";
import { IconPrinter } from "@tabler/icons-react";
import { Link, useParams } from "react-router-dom";

import { useServices, useServiceTypes, useVehicle } from "../api/hooks";
import { day, km, money } from "../lib/format";

/** Printable service history, e.g. for a buyer. Rendered outside the app shell. */
export default function History() {
  const id = Number(useParams().id);
  const vehicle = useVehicle(id);
  const services = useServices(id);
  useServiceTypes();
  if (vehicle.isLoading || services.isLoading) return <Loader m="xl" />;
  const v = vehicle.data;
  const list = [...(services.data ?? [])].sort((a, b) => a.date.localeCompare(b.date));
  const total = list.reduce((s, r) => s + r.cost_cents, 0);
  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: 24 }}>
      <style>{`@media print { .no-print { display: none !important; } body { background: white; color: black; } }`}</style>
      <Group justify="space-between" className="no-print" mb="md">
        <Button component={Link} to={`/vehicles/${id}`} variant="default">Back</Button>
        <Button leftSection={<IconPrinter size={16} />} onClick={() => window.print()}>Print</Button>
      </Group>
      <Title order={2}>Service history: {v?.year} {v?.make} {v?.model}</Title>
      <Text c="dimmed" mb="md">
        {v?.nickname}{v?.vin ? ` · VIN ${v.vin}` : ""} · {km(v?.current_km)} · printed {day(new Date().toISOString())}
      </Text>
      <Table withTableBorder withColumnBorders>
        <Table.Thead>
          <Table.Tr><Table.Th>Date</Table.Th><Table.Th>Work</Table.Th><Table.Th>Shop</Table.Th>
            <Table.Th ta="right">Odometer</Table.Th><Table.Th ta="right">Cost</Table.Th><Table.Th>Receipts</Table.Th></Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {list.map((s) => (
            <Table.Tr key={s.id}>
              <Table.Td>{day(s.date)}</Table.Td>
              <Table.Td>{s.type_names.join(", ") || s.notes || "Service"}</Table.Td>
              <Table.Td>{s.vendor ?? ""}</Table.Td>
              <Table.Td ta="right">{km(s.odometer_km)}</Table.Td>
              <Table.Td ta="right">{money(s.cost_cents)}</Table.Td>
              <Table.Td>{s.attachments.length ? `${s.attachments.length} on file` : ""}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
        <Table.Tfoot>
          <Table.Tr><Table.Th colSpan={4} ta="right">Total</Table.Th><Table.Th ta="right">{money(total)}</Table.Th><Table.Th /></Table.Tr>
        </Table.Tfoot>
      </Table>
      {list.length === 0 && <Text mt="md" c="dimmed">No services recorded.</Text>}
    </div>
  );
}
