import React from 'react';
import {
  Card,
  Text,
  Badge,
  Group,
  Stack,
  Progress,
  Paper,
  Box,
  Timeline,
  ThemeIcon,
} from '@mantine/core';
import {
  IconPlane,
  IconMapPin,
  IconReceipt,
  IconShieldCheck,
} from '@tabler/icons-react';
import { TripItem } from '../types';

interface Props {
  trips: TripItem[];
}

export const TripsView: React.FC<Props> = ({ trips }) => {
  return (
    <Stack gap="md">
      {/* 1. Header & Inverted Geofence Banner */}
      <Card withBorder radius="md" p="md" bg="grape.0" style={{ borderColor: 'var(--mantine-color-grape-2)' }}>
        <Group justify="space-between" align="flex-start">
          <Box>
            <Text fw={800} size="md" c="grape.9">
              Travel & Multi-Stop Trips Engine
            </Text>
            <Text size="xs" c="dark.3">
              Inverted Home Geofence (&gt; 30 miles from Cranberry Twp, PA) automatically captures vacation dining & receipts.
            </Text>
          </Box>
          <Badge color="grape" variant="light">Inverted Geofence</Badge>
        </Group>

        <Group gap="xs" mt="sm">
          <ThemeIcon size="xs" color="grape" radius="xl">
            <IconShieldCheck size={12} />
          </ThemeIcon>
          <Text size="11px" c="grape.9" fw={500}>
            Home utilities, lawn service, and internet bills are strictly excluded from trip budgets.
          </Text>
        </Group>
      </Card>

      {/* 2. Active Trips */}
      {trips.map((trip) => {
        const pct = Math.min(100, (trip.spent / trip.budget) * 100);
        return (
          <Card key={trip.id} withBorder radius="md" p="md">
            <Group justify="space-between" mb="xs">
              <Group gap="xs">
                <ThemeIcon color="grape" size="md" radius="xl">
                  <IconPlane size={18} />
                </ThemeIcon>
                <Box>
                  <Text fw={700} size="md">
                    {trip.name}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {trip.start_date} to {trip.end_date}
                  </Text>
                </Box>
              </Group>
              <Badge color="grape" size="sm">Active Trip</Badge>
            </Group>

            {/* Budget Progress */}
            <Box mb="md">
              <Group justify="space-between" mb={4}>
                <Text size="xs" fw={600}>
                  Budget Utilization
                </Text>
                <Text size="xs" fw={700} c="grape.8">
                  ${trip.spent.toLocaleString()} / ${trip.budget.toLocaleString()} ({pct.toFixed(0)}%)
                </Text>
              </Group>
              <Progress value={pct} color="grape" size="sm" />
            </Box>

            {/* Ordered Itinerary Stops */}
            <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb="xs">
              Ordered Stops & Attributed Expenses
            </Text>
            <Timeline active={trip.stops.length} bulletSize={22} lineWidth={2}>
              {trip.stops.map((stop, i) => (
                <Timeline.Item
                  key={i}
                  bullet={<IconMapPin size={12} />}
                  title={
                    <Group justify="space-between">
                      <Text size="sm" fw={600}>
                        {stop.name}
                      </Text>
                      <Badge size="xs" variant="light" color="green">
                        ${stop.spent}
                      </Badge>
                    </Group>
                  }
                >
                  <Text size="xs" c="dimmed">
                    Arrived: {stop.date}
                  </Text>
                </Timeline.Item>
              ))}
            </Timeline>
          </Card>
        );
      })}
    </Stack>
  );
};
