import type { components } from "./schema";

type S = components["schemas"];
export type Vehicle = S["VehicleOut"];
export type Dashboard = S["DashboardOut"];
export type StatusItem = S["StatusItemOut"];
export type Service = S["ServiceOut"];
export type ServiceType = S["ServiceTypeOut"];
export type Odometer = S["OdometerOut"];
export type Rule = S["RuleOut"];
export type DateItem = S["DateItemOut"];
export type TireSet = S["TireSetOut"];
export type Report = S["ReportOut"];
export type RecurringCost = S["RecurringCostOut"];
export type Spending = S["SpendingOut"];
export type SpendingEntry = S["SpendingEntry"];
