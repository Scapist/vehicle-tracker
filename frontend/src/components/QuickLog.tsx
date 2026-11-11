import {
  Alert, Button, Checkbox, FileButton, Group, Modal, MultiSelect, NumberInput, Select, Stack, Tabs, Text,
  Textarea, TextInput,
} from "@mantine/core";
import { DateInput } from "@mantine/dates";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconCamera, IconGauge, IconPaperclip, IconReceipt, IconTool } from "@tabler/icons-react";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, ApiError } from "../api/client";
import { useInvalidate, useServices, useServiceTypes, useVehicles } from "../api/hooks";
import type { Odometer, Service, Vehicle } from "../api/types";
import { isoDate, km, toCents } from "../lib/format";
import { notifyError, notifyUndo } from "./status";

type Tab = "mileage" | "service" | "receipt";
type Ctx = { open: (tab?: Tab, vehicleId?: number) => void };
const QuickLogContext = createContext<Ctx>({ open: () => {} });
export const useQuickLog = () => useContext(QuickLogContext);

export function QuickLogProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ tab: Tab; vehicleId?: number } | null>(null);
  const mobile = useMediaQuery("(max-width: 48em)");
  const vehicles = useVehicles();
  const ctx = useMemo<Ctx>(() => ({ open: (tab = "mileage", vehicleId) => setState({ tab, vehicleId }) }), []);
  const close = () => setState(null);
  return (
    <QuickLogContext.Provider value={ctx}>
      {children}
      <Modal opened={!!state} onClose={close} title="Quick log" fullScreen={!!mobile} size="lg"
        keepMounted={false}>
        {state && (vehicles.data?.length ? (
          <Tabs keepMounted={false} value={state.tab} onChange={(t) => setState({ ...state, tab: t as Tab })}>
            <Tabs.List mb="md">
              <Tabs.Tab value="mileage" leftSection={<IconGauge size={16} />}>Mileage</Tabs.Tab>
              <Tabs.Tab value="service" leftSection={<IconTool size={16} />}>Service</Tabs.Tab>
              <Tabs.Tab value="receipt" leftSection={<IconReceipt size={16} />}>Receipt</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="mileage"><MileageForm vehicles={vehicles.data} initial={state.vehicleId} onDone={close} /></Tabs.Panel>
            <Tabs.Panel value="service"><ServiceForm vehicles={vehicles.data} initial={state.vehicleId} onDone={close} /></Tabs.Panel>
            <Tabs.Panel value="receipt"><ReceiptForm vehicles={vehicles.data} initial={state.vehicleId} onDone={close} /></Tabs.Panel>
          </Tabs>
        ) : (
          <Text>Add a vehicle first (Vehicles page).</Text>
        ))}
      </Modal>
    </QuickLogContext.Provider>
  );
}

function useVehiclePick(vehicles: Vehicle[], initial?: number) {
  const [id, setId] = useState<string>(String(initial ?? vehicles[0]?.id));
  const vehicle = vehicles.find((v) => String(v.id) === id) ?? vehicles[0];
  const select = vehicles.length > 1 ? (
    <Select label="Vehicle" data={vehicles.map((v) => ({ value: String(v.id), label: v.nickname }))}
      value={id} onChange={(v) => v && setId(v)} allowDeselect={false} />
  ) : null;
  return { vehicle, select };
}

type FormProps = { vehicles: Vehicle[]; initial?: number; onDone: () => void };

export function MileageForm({ vehicles, initial, onDone }: FormProps) {
  const { vehicle, select } = useVehiclePick(vehicles, initial);
  const [value, setValue] = useState<number | string>(vehicle.current_km ?? "");
  const [correction, setCorrection] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const invalidate = useInvalidate();
  // switching vehicle must not carry over the previous vehicle's odometer
  useEffect(() => {
    setValue(vehicle.current_km ?? "");
    setCorrection(false);
    setError(null);
  }, [vehicle.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<Odometer>(`/vehicles/${vehicle.id}/odometer`, {
        method: "POST", json: { km: Number(value), is_correction: correction },
      });
      await invalidate();
      onDone();
      if (!correction) {
        notifyUndo(`${vehicle.nickname}: ${km(r.km)} logged`, async () => {
          await api(`/vehicles/${vehicle.id}/odometer/${r.id}`, { method: "DELETE" });
          await invalidate();
        });
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) setError(e.message);
      else notifyError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stack>
      {select}
      <NumberInput label="Odometer (km)" value={value} onChange={setValue} thousandSeparator=","
        min={0} allowNegative={false} data-autofocus inputMode="numeric"
        description={vehicle.current_km != null ? `Current: ${km(vehicle.current_km)}` : "First reading"} />
      {error && (
        <Alert color="orange" title="Lower than the current reading">
          {error}
          <Checkbox mt="xs" label="Yes, this is a correction" checked={correction}
            onChange={(e) => setCorrection(e.currentTarget.checked)} />
        </Alert>
      )}
      <Button onClick={submit} loading={busy} disabled={value === ""}>Save mileage</Button>
    </Stack>
  );
}

function FilePicker({ files, setFiles }: { files: File[]; setFiles: (f: File[]) => void }) {
  const add = (f: File[] | File | null) => f && setFiles([...files, ...(Array.isArray(f) ? f : [f])]);
  return (
    <Stack gap={4}>
      <Group gap="xs">
        <FileButton onChange={add} multiple accept="image/jpeg,image/png,image/webp,image/heic,application/pdf">
          {(p) => <Button {...p} variant="default" leftSection={<IconPaperclip size={16} />}>Choose files</Button>}
        </FileButton>
        <FileButton onChange={add} accept="image/*" inputProps={{ capture: "environment" }}>
          {(p) => <Button {...p} variant="default" leftSection={<IconCamera size={16} />}>Take photo</Button>}
        </FileButton>
      </Group>
      {files.map((f, i) => (
        <Group key={i} gap="xs">
          <Text size="sm">{f.name} ({Math.round(f.size / 1024)} KB)</Text>
          <Button size="compact-xs" variant="subtle" color="red"
            onClick={() => setFiles(files.filter((_, j) => j !== i))}>Remove</Button>
        </Group>
      ))}
    </Stack>
  );
}

export function ServiceForm({ vehicles, initial, onDone }: FormProps) {
  const { vehicle, select } = useVehiclePick(vehicles, initial);
  const types = useServiceTypes();
  const [date, setDate] = useState<Date | null>(new Date());
  const [odo, setOdo] = useState<number | string>(vehicle.current_km ?? "");
  const [typeIds, setTypeIds] = useState<string[]>([]);
  const [cost, setCost] = useState<number | string>("");
  const [vendor, setVendor] = useState("");
  const [notes, setNotes] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const invalidate = useInvalidate();
  useEffect(() => {
    setOdo(vehicle.current_km ?? "");
  }, [vehicle.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit() {
    setBusy(true);
    try {
      const fd = new FormData();
      fd.set("vehicle_id", String(vehicle.id));
      fd.set("date", isoDate(date));
      if (odo !== "") fd.set("odometer_km", String(odo));
      fd.set("cost_cents", String(toCents(cost)));
      if (vendor) fd.set("vendor", vendor);
      if (notes) fd.set("notes", notes);
      typeIds.forEach((t) => fd.append("type_ids", t));
      files.forEach((f) => fd.append("files", f));
      const rec = await api<Service>("/services", { method: "POST", body: fd });
      await invalidate();
      onDone();
      notifyUndo(`Service logged for ${vehicle.nickname}`, async () => {
        await api(`/services/${rec.id}`, { method: "DELETE" });
        await invalidate();
      });
    } catch (e) {
      notifyError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stack>
      {select}
      <MultiSelect label="What was done?" placeholder="Pick one or more"
        data={(types.data ?? []).map((t) => ({ value: String(t.id), label: t.name }))}
        value={typeIds} onChange={setTypeIds} searchable />
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
      <Button onClick={submit} loading={busy} disabled={!date}>Save service</Button>
    </Stack>
  );
}

export function ReceiptForm({ vehicles, initial, onDone }: FormProps) {
  const { vehicle, select } = useVehiclePick(vehicles, initial);
  const services = useServices(vehicle.id);
  const [target, setTarget] = useState<string>("new");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const invalidate = useInvalidate();
  useEffect(() => {
    setTarget("new"); // a service from the previous vehicle must not stay selected
  }, [vehicle.id]);
  const options = [
    { value: "new", label: "New receipt-only entry" },
    ...(services.data ?? []).slice(0, 15).map((s) => ({
      value: String(s.id), label: `${s.date} · ${s.type_names.join(", ") || s.vendor || "Service"}`,
    })),
  ];

  async function submit() {
    setBusy(true);
    try {
      if (target === "new") {
        const fd = new FormData();
        fd.set("vehicle_id", String(vehicle.id));
        fd.set("date", isoDate(new Date()));
        fd.set("notes", "Receipt only");
        files.forEach((f) => fd.append("files", f));
        await api("/services", { method: "POST", body: fd });
      } else {
        for (const f of files) {
          const fd = new FormData();
          fd.set("file", f);
          await api(`/services/${target}/attachments`, { method: "POST", body: fd });
        }
      }
      await invalidate();
      onDone();
      notifications.show({ color: "green", message: "Receipt saved" });
    } catch (e) {
      notifyError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stack>
      {select}
      <Select label="Attach to" data={options} value={target} onChange={(v) => v && setTarget(v)} allowDeselect={false} />
      <FilePicker files={files} setFiles={setFiles} />
      <Button onClick={submit} loading={busy} disabled={!files.length}>Save receipt</Button>
    </Stack>
  );
}
