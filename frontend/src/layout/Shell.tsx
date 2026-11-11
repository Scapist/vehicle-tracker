import {
  Affix, AppShell, Button, Group, NavLink, Stack, Text, ThemeIcon, Title, UnstyledButton,
  ActionIcon, useComputedColorScheme, useMantineColorScheme, rem,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import {
  IconCar, IconChartBar, IconCircleDot, IconHome, IconMoon, IconPlus, IconSettings, IconSun,
} from "@tabler/icons-react";
import type { ReactNode } from "react";
import { NavLink as RouterLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useQuickLog } from "../components/QuickLog";

const NAV = [
  { to: "/", label: "Dashboard", icon: IconHome },
  { to: "/vehicles", label: "Vehicles", icon: IconCar },
  { to: "/tires", label: "Tires", icon: IconCircleDot },
  { to: "/reports", label: "Reports", icon: IconChartBar },
  { to: "/settings", label: "Settings", icon: IconSettings },
];

function ThemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light", { getInitialValueInEffect: true });
  return (
    <ActionIcon variant="default" size="lg" aria-label="Toggle dark mode"
      onClick={() => setColorScheme(scheme === "dark" ? "light" : "dark")}>
      {scheme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
    </ActionIcon>
  );
}

export default function Shell(): ReactNode {
  const mobile = useMediaQuery("(max-width: 48em)", false, { getInitialValueInEffect: false });
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const quick = useQuickLog();
  // on a vehicle page, Quick log defaults to that vehicle
  const currentVehicleId = Number(pathname.match(/^\/vehicles\/(\d+)/)?.[1]) || undefined;
  const active = (to: string) => (to === "/" ? pathname === "/" : pathname.startsWith(to));

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 220, breakpoint: "sm", collapsed: { mobile: true } }}
      footer={{ height: 64, collapsed: !mobile }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <ThemeIcon variant="light" size="lg"><IconCar size={20} /></ThemeIcon>
            <Title order={4}>Vehicle Tracker</Title>
          </Group>
          <Group gap="xs" wrap="nowrap">
            {!mobile && (
              <Button leftSection={<IconPlus size={16} />} onClick={() => quick.open("mileage", currentVehicleId)}>Quick log</Button>
            )}
            <ThemeToggle />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <Stack gap={2}>
          {NAV.map((n) => (
            <NavLink key={n.to} component={RouterLink} to={n.to} label={n.label} active={active(n.to)}
              leftSection={<n.icon size={18} />} />
          ))}
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main pb={mobile ? 96 : undefined}>
        <Outlet />
      </AppShell.Main>

      <AppShell.Footer>
        <Group h="100%" justify="space-around" wrap="nowrap" component="nav" aria-label="Main">
          {NAV.map((n) => (
            <UnstyledButton key={n.to} onClick={() => navigate(n.to)} aria-label={n.label}
              aria-current={active(n.to) ? "page" : undefined} style={{ flex: 1, padding: rem(6) }}>
              <Stack gap={2} align="center" c={active(n.to) ? "blue" : "dimmed"}>
                <n.icon size={22} />
                <Text size="xs" fw={active(n.to) ? 700 : 400}>{n.label}</Text>
              </Stack>
            </UnstyledButton>
          ))}
        </Group>
      </AppShell.Footer>

      {mobile && (
        <Affix position={{ bottom: 78, right: 16 }}>
          <Button size="md" radius="xl" leftSection={<IconPlus size={18} />} onClick={() => quick.open("mileage", currentVehicleId)}
            style={{ boxShadow: "var(--mantine-shadow-md)" }}>
            Quick log
          </Button>
        </Affix>
      )}
    </AppShell>
  );
}

