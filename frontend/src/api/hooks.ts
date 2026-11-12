import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  Dashboard, DateItem, Odometer, RecurringCost, Report, Rule, Service, ServiceType, Spending, TireSet, Vehicle,
} from "./types";

export const useVehicles = () => useQuery({ queryKey: ["vehicles"], queryFn: () => api<Vehicle[]>("/vehicles") });
export const useVehicle = (id: number) =>
  useQuery({ queryKey: ["vehicles", id], queryFn: () => api<Vehicle>(`/vehicles/${id}`) });
export const useDashboard = (id: number) =>
  useQuery({ queryKey: ["dashboard", id], queryFn: () => api<Dashboard>(`/vehicles/${id}/dashboard`) });
export const useServiceTypes = () =>
  useQuery({ queryKey: ["service-types"], queryFn: () => api<ServiceType[]>("/service-types"), staleTime: Infinity });
export const useServices = (id: number) =>
  useQuery({ queryKey: ["services", id], queryFn: () => api<Service[]>(`/vehicles/${id}/services`) });
export const useOdometer = (id: number) =>
  useQuery({ queryKey: ["odometer", id], queryFn: () => api<Odometer[]>(`/vehicles/${id}/odometer`) });
export const useRules = (id: number) =>
  useQuery({ queryKey: ["rules", id], queryFn: () => api<Rule[]>(`/vehicles/${id}/rules`) });
export const useDateItems = (vehicleId?: number) =>
  useQuery({
    queryKey: ["date-items", vehicleId ?? "all"],
    queryFn: () => api<DateItem[]>(`/date-items${vehicleId ? `?vehicle_id=${vehicleId}` : ""}`),
  });
export const useTireSets = (vehicleId?: number) =>
  useQuery({
    queryKey: ["tire-sets", vehicleId ?? "all"],
    queryFn: () => api<TireSet[]>(`/tire-sets${vehicleId ? `?vehicle_id=${vehicleId}` : ""}`),
  });
export const useReport = (vehicle?: number, year?: number) =>
  useQuery({
    queryKey: ["report", vehicle ?? "all", year ?? "all"],
    queryFn: () => {
      const q = new URLSearchParams();
      if (vehicle) q.set("vehicle", String(vehicle));
      if (year) q.set("year", String(year));
      return api<Report>(`/reports?${q}`);
    },
  });
export const useRecurringCosts = (vehicleId: number) =>
  useQuery({
    queryKey: ["recurring-costs", vehicleId],
    queryFn: () => api<RecurringCost[]>(`/vehicles/${vehicleId}/recurring-costs`),
  });

export type SpendingFilter = { from: string; to: string; vehicle?: number; categories: string[] };

/** The same query string for the JSON and the CSV export, so the download matches the screen. */
export function spendingQuery(f: SpendingFilter) {
  const q = new URLSearchParams({ from: f.from, to: f.to });
  if (f.vehicle) q.set("vehicle", String(f.vehicle));
  f.categories.forEach((c) => q.append("category", c));
  return q.toString();
}

export const useSpending = (f: SpendingFilter) =>
  useQuery({
    queryKey: ["spending", spendingQuery(f)],
    queryFn: () => api<Spending>(`/spending?${spendingQuery(f)}`),
    placeholderData: (prev) => prev,  // keep the old numbers on screen while a new filter loads
  });

/** Everything on screen can depend on odometer, services, rules or dates, so refresh it all after a write. */
export function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}

export function useApiMutation<TVars, TOut = unknown>(fn: (v: TVars) => Promise<TOut>) {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: fn, onSuccess: () => invalidate() });
}
