import { Alert, Anchor, Button, Card, Group, Loader, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { Link } from "react-router-dom";

import { useDashboard, useVehicles } from "../api/hooks";
import type { Vehicle } from "../api/types";
import { ItemCard } from "../components/ItemCard";
import { useQuickLog } from "../components/QuickLog";
import { km, money } from "../lib/format";

function VehicleCard({ vehicle }: { vehicle: Vehicle }) {
  const dash = useDashboard(vehicle.id);
  const quick = useQuickLog();
  const attention = (dash.data?.items ?? []).filter(
    (i) => (i.status === "overdue" || i.status === "due_soon" || i.status === "unknown") && !i.informational);
  return (
    <Card withBorder padding="md" radius="md">
      <Stack>
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <div>
            <Anchor component={Link} to={`/vehicles/${vehicle.id}`} fw={700} size="lg" c="inherit">
              {vehicle.nickname}
            </Anchor>
            <Text size="sm" c="dimmed">{vehicle.year} {vehicle.make} {vehicle.model} · {km(vehicle.current_km)}</Text>
          </div>
          <Button size="compact-md" variant="light" onClick={() => quick.open("mileage", vehicle.id)}>Update km</Button>
        </Group>
        {dash.isLoading && <Loader size="sm" />}
        {dash.data && attention.length === 0 && (
          <Alert color="green" icon={<IconCheck size={18} />} title="All good">Nothing needs attention right now.</Alert>
        )}
        {attention.slice(0, 4).map((i) => <ItemCard key={i.subject} item={i} compact={false} />)}
        {attention.length > 4 && (
          <Anchor component={Link} to={`/vehicles/${vehicle.id}`} size="sm">+{attention.length - 4} more</Anchor>
        )}
        {dash.data && (
          <Text size="sm" c="dimmed">{dash.data.year} spend: {money(dash.data.year_cost_cents)}</Text>
        )}
      </Stack>
    </Card>
  );
}

export default function Dashboard() {
  const vehicles = useVehicles();
  if (vehicles.isLoading) return <Loader />;
  if (!vehicles.data?.length) {
    return (
      <Stack align="flex-start">
        <Title order={2}>Dashboard</Title>
        <Text>No vehicles yet. Add your first one to start tracking mileage and maintenance.</Text>
        <Button component={Link} to="/vehicles">Add a vehicle</Button>
      </Stack>
    );
  }
  return (
    <Stack>
      <Title order={2}>Dashboard</Title>
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="md">
        {vehicles.data.map((v) => <VehicleCard key={v.id} vehicle={v} />)}
      </SimpleGrid>
    </Stack>
  );
}
