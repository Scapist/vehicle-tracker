import { MultiSelect, Select } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { useServiceTypes } from "../api/hooks";
import type { ServiceType } from "../api/types";
import { notifyError } from "./status";

const NEW = "__new__:";

/** Options for the service pickers: every service you can use, plus "+ Add …" when the search text
 * doesn't match one, so a service that isn't in the list can be created on the spot. */
function useOptions(search: string, include?: (t: ServiceType) => boolean) {
  const types = useServiceTypes();
  const qc = useQueryClient();
  const list = (types.data ?? []).filter((t) => !include || include(t));
  const data = list.map((t) => ({ value: String(t.id), label: t.name }));
  const typed = search.trim().replace(/\s+/g, " ");
  if (typed && !(types.data ?? []).some((t) => t.name.toLowerCase() === typed.toLowerCase())) {
    data.push({ value: NEW + typed, label: `+ Add “${typed}”` });
  }

  /** Turns a "+ Add" choice into a real service type and returns its id. */
  async function resolve(value: string): Promise<string | null> {
    if (!value.startsWith(NEW)) return value;
    try {
      const t = await api<ServiceType>("/service-types", { method: "POST", json: { name: value.slice(NEW.length) } });
      await qc.invalidateQueries({ queryKey: ["service-types"] });
      return String(t.id);
    } catch (e) {
      notifyError(e);
      return null;
    }
  }
  return { data, resolve };
}

export function ServiceTypeMultiPicker({ value, onChange, label }: {
  value: string[]; onChange: (v: string[]) => void; label: string;
}) {
  const [search, setSearch] = useState("");
  const { data, resolve } = useOptions(search);
  return (
    <MultiSelect label={label} placeholder={value.length ? undefined : "Pick one or more, or type a new one"}
      data={data} value={value} searchable searchValue={search} onSearchChange={setSearch}
      nothingFoundMessage="Type a name to add it"
      onChange={async (next) => {
        const created = next.find((v) => v.startsWith(NEW));
        if (!created) return onChange(next);
        setSearch("");
        const id = await resolve(created);
        onChange(next.filter((v) => v !== created).concat(id && !next.includes(id) ? [id] : []));
      }} />
  );
}

export function ServiceTypeSelect({ value, onChange, label, include }: {
  value: string | null; onChange: (v: string | null) => void; label: string; include?: (t: ServiceType) => boolean;
}) {
  const [search, setSearch] = useState("");
  const { data, resolve } = useOptions(search, include);
  return (
    <Select label={label} placeholder="Pick one, or type a new one" data={data} value={value} searchable
      searchValue={search} onSearchChange={setSearch} nothingFoundMessage="Type a name to add it"
      onChange={async (v) => {
        if (!v || !v.startsWith(NEW)) return onChange(v);
        const id = await resolve(v);
        onChange(id);
      }} />
  );
}
