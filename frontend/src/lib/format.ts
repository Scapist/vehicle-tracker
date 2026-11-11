import dayjs from "dayjs";

export const km = (n: number | null | undefined) => (n == null ? "—" : `${n.toLocaleString("en-CA")} km`);

export const money = (cents: number | null | undefined) =>
  cents == null ? "—" : (cents / 100).toLocaleString("en-CA", { style: "currency", currency: "CAD" });

export const day = (iso: string | null | undefined) => (iso ? dayjs(iso).format("MMM D, YYYY") : "—");

/** Dollars typed by the user -> integer cents. */
export const toCents = (v: string | number | undefined | null) => {
  const n = typeof v === "number" ? v : parseFloat(String(v ?? "").replace(/[$,\s]/g, ""));
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
};

export const isoDate = (d: Date | string | null | undefined) => dayjs(d ?? undefined).format("YYYY-MM-DD");
