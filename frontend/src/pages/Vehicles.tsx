import { Button, Card, Group, Modal, NumberInput, SimpleGrid, Stack, Text, TextInput, Title } from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { IconPlus } from "@tabler/icons-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation, useVehicles } from "../api/hooks";
import type { Vehicle } from "../api/types";
import { notifyError, StatusBadge } from "../components/status";
import { km } from "../lib/format";

export function AddVehicleModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const mobile = useMediaQuery("(max-width: 48em)");
  const [f, setF] = useState({ nickname: "", make: "", model: "", year: new Date().getFullYear() as number | string, vin: "" });
  const create = useApiMutation((b: object) => api("/vehicles", { method: "POST", json: b }));
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.currentTarget.value });
  async function submit() {
    try {
      await create.mutateAsync({ ...f, year: Number(f.year), vin: f.vin || null });
      onClose();
    } catch (e) {
      notifyError(e);
    }
  }
  return (
    <Modal opened={opened} onClose={onClose} title="Add vehicle" fullScreen={!!mobile}>
      <Stack>
        <TextInput label="Nickname" description="Used by the Telegram bot, e.g. “civic 84500”" value={f.nickname} onChange={set("nickname")} data-autofocus />
        <Group grow>
          <TextInput label="Make" value={f.make} onChange={set("make")} />
          <TextInput label="Model" value={f.model} onChange={set("model")} />
        </Group>
        <NumberInput label="Year" value={f.year} onChange={(v) => setF({ ...f, year: v })} min={1900} max={2100} />
        <TextInput label="VIN (optional)" value={f.vin} onChange={set("vin")} />
        <Button onClick={submit} loading={create.isPending} disabled={!f.nickname || !f.make || !f.model}>Add vehicle</Button>
      </Stack>
    </Modal>
  );
}

function Row({ v }: { v: Vehicle }) {
  return (
    <Card withBorder component={Link} to={`/vehicles/${v.id}`} padding="md" style={{ textDecoration: "none", color: "inherit" }}>
      <Group justify="space-between" wrap="nowrap">
        <div>
          <Text fw={700}>{v.nickname}</Text>
          <Text size="sm" c="dimmed">{v.year} {v.make} {v.model} · {km(v.current_km)}</Text>
        </div>
        <StatusBadge status={v.worst_status} />
      </Group>
    </Card>
  );
}

export default function Vehicles() {
  const vehicles = useVehicles();
  const [opened, { open, close }] = useDisclosure(false);
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Vehicles</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={open}>Add vehicle</Button>
      </Group>
      {vehicles.data?.length === 0 && <Text c="dimmed">No vehicles yet. Add one to get started.</Text>}
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>{vehicles.data?.map((v) => <Row key={v.id} v={v} />)}</SimpleGrid>
      <AddVehicleModal opened={opened} onClose={close} />
    </Stack>
  );
}
