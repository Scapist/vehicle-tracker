import {
  Badge, Button, Card, Group, Modal, NumberInput, Select, SimpleGrid, Stack, Text, TextInput, Title,
} from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconPlus } from "@tabler/icons-react";
import { useState } from "react";

import { api } from "../api/client";
import { useApiMutation, useTireSets, useVehicles } from "../api/hooks";
import type { TireSet } from "../api/types";
import { notifyError } from "../components/status";
import { day, km, money, toCents } from "../lib/format";

function SetCard({ ts }: { ts: TireSet }) {
  const [treadOpen, tread] = useDisclosure(false);
  const [depth, setDepth] = useState<number | string>("");
  const act = useApiMutation((a: { path: string; json?: object }) => api(a.path, { method: "POST", json: a.json ?? {} }));
  const patch = useApiMutation((body: object) => api(`/tire-sets/${ts.id}`, { method: "PATCH", json: body }));
  const run = async (path: string, ok: string, json?: object) => {
    try {
      await act.mutateAsync({ path, json });
      notifications.show({ color: "green", message: ok });
    } catch (e) {
      notifyError(e);
    }
  };
  const threshold = ts.season === "winter" ? 4 : 3;
  return (
    <Card withBorder padding="md" opacity={ts.retired ? 0.6 : 1}>
      <Stack gap="xs">
        <Group justify="space-between" wrap="wrap" align="flex-start" gap="xs">
          <div>
            <Text fw={700}>{ts.label}</Text>
            <Text size="sm" c="dimmed">{[ts.brand_model, ts.size].filter(Boolean).join(" · ") || ts.season}</Text>
          </div>
          <Group gap={4}>
            {ts.mounted && <Badge color="green">On the car</Badge>}
            {ts.retired && <Badge color="gray">Retired</Badge>}
            <Badge variant="light">{ts.season.replace("_", " ")}</Badge>
          </Group>
        </Group>
        <Text size="sm">Driven: {km(ts.total_km)}{ts.cost_cents ? ` · bought for ${money(ts.cost_cents)}` : ""}</Text>
        {ts.storage_location && <Text size="sm" c="dimmed">Stored: {ts.storage_location}</Text>}
        {ts.latest_tread_mm != null && (
          <Group gap={6}>
            {ts.tread_warning && <IconAlertTriangle size={16} color="var(--mantine-color-orange-6)" />}
            <Text size="sm" c={ts.tread_warning ? "orange" : undefined} fw={ts.tread_warning ? 600 : 400}>
              Tread {ts.latest_tread_mm} mm{ts.tread_warning ? ` (at or below ${threshold} mm: time to replace)` : ""}
            </Text>
          </Group>
        )}
        {ts.treads.length > 0 && (
          <Text size="xs" c="dimmed">
            Measured: {[...ts.treads].sort((a, b) => a.date.localeCompare(b.date)).map((t) => `${day(t.date)} ${t.depth_mm} mm`).join(" → ")}
          </Text>
        )}
        {!ts.retired && (
          <Group gap="xs">
            {ts.mounted
              ? <Button size="compact-sm" variant="default" onClick={() => run(`/tire-sets/${ts.id}/unmount`, "Taken off")}>Take off</Button>
              : <Button size="compact-sm" onClick={() => run(`/tire-sets/${ts.id}/mount`, "Mounted (other set taken off)")}>Mount</Button>}
            <Button size="compact-sm" variant="default" onClick={tread.open}>Add tread reading</Button>
            {!ts.mounted && <Button size="compact-sm" variant="subtle" color="gray" onClick={() => patch.mutate({ retired: true })}>Retire</Button>}
          </Group>
        )}
      </Stack>
      <Modal opened={treadOpen} onClose={tread.close} title={`Tread depth: ${ts.label}`}>
        <Stack>
          <NumberInput label="Depth (mm)" value={depth} onChange={setDepth} decimalScale={1} min={0} max={20} step={0.5} data-autofocus />
          <Button disabled={depth === ""} onClick={async () => { await run(`/tire-sets/${ts.id}/tread`, "Saved", { depth_mm: Number(depth) }); tread.close(); setDepth(""); }}>Save</Button>
        </Stack>
      </Modal>
    </Card>
  );
}

function AddSet({ vehicleId, opened, onClose }: { vehicleId: number; opened: boolean; onClose: () => void }) {
  const mobile = useMediaQuery("(max-width: 48em)");
  const [f, setF] = useState({ label: "", season: "winter", size: "", brand_model: "", dot_code: "", storage_location: "" });
  const [cost, setCost] = useState<number | string>("");
  const create = useApiMutation((b: object) => api("/tire-sets", { method: "POST", json: b }));
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.currentTarget.value });
  async function submit() {
    try {
      await create.mutateAsync({
        vehicle_id: vehicleId, ...f, size: f.size || null, brand_model: f.brand_model || null,
        dot_code: f.dot_code || null, storage_location: f.storage_location || null,
        cost_cents: cost === "" ? null : toCents(cost),
      });
      onClose();
    } catch (e) { notifyError(e); }
  }
  return (
    <Modal opened={opened} onClose={onClose} title="Add tire set" fullScreen={!!mobile}>
      <Stack>
        <TextInput label="Label" placeholder="e.g. Winter 2025" value={f.label} onChange={set("label")} data-autofocus />
        <Select label="Season" value={f.season} onChange={(v) => v && setF({ ...f, season: v })} allowDeselect={false}
          data={[{ value: "winter", label: "Winter" }, { value: "summer", label: "Summer" }, { value: "all_season", label: "All-season" }]} />
        <Group grow>
          <TextInput label="Size" placeholder="205/55R16" value={f.size} onChange={set("size")} />
          <TextInput label="Brand / model" value={f.brand_model} onChange={set("brand_model")} />
        </Group>
        <Group grow>
          <TextInput label="DOT code" value={f.dot_code} onChange={set("dot_code")} />
          <NumberInput label="Cost" leftSection="$" value={cost} onChange={setCost} decimalScale={2} min={0} />
        </Group>
        <TextInput label="Storage location" value={f.storage_location} onChange={set("storage_location")} />
        <Button onClick={submit} loading={create.isPending} disabled={!f.label}>Add set</Button>
      </Stack>
    </Modal>
  );
}

export default function Tires() {
  const vehicles = useVehicles();
  const [vid, setVid] = useState<string | null>(null);
  const vehicleId = Number(vid ?? vehicles.data?.[0]?.id);
  const sets = useTireSets(vehicleId || undefined);
  const [adding, add] = useDisclosure(false);
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Tires</Title>
        <Group>
          {(vehicles.data?.length ?? 0) > 1 && (
            <Select aria-label="Vehicle" data={vehicles.data!.map((v) => ({ value: String(v.id), label: v.nickname }))}
              value={String(vehicleId)} onChange={setVid} allowDeselect={false} w={160} />
          )}
          {vehicleId > 0 && <Button leftSection={<IconPlus size={16} />} onClick={add.open}>Add set</Button>}
        </Group>
      </Group>
      {vehicleId > 0 && sets.data?.length === 0 && <Text c="dimmed">No tire sets yet. Add your summer and winter sets to track kilometres and tread.</Text>}
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>{sets.data?.map((t) => <SetCard key={t.id} ts={t} />)}</SimpleGrid>
      {vehicleId > 0 && <AddSet vehicleId={vehicleId} opened={adding} onClose={add.close} />}
    </Stack>
  );
}
