import React, { useState } from 'react';
import {
  Card,
  Text,
  Badge,
  Group,
  Stack,
  Button,
  Tabs,
  Progress,
  ThemeIcon,
  Box,
  Paper,
  Divider,
} from '@mantine/core';
import {
  IconAlertTriangle,
  IconShoppingCart,
  IconCheck,
  IconX,
  IconBell,
  IconConfetti,
} from '@tabler/icons-react';
import { ConflictItem, DepletionProposal } from '../types';
import { ConflictTriageCenter } from './ConflictTriageCenter';

interface Props {
  conflicts: ConflictItem[];
  depletions: DepletionProposal[];
  onResolveConflict: (id: string) => void;
  onRescheduleConflict: (id: string) => void;
  onConfirmDepletion: (id: string) => void;
  onDismissDepletion: (id: string) => void;
  onRecheckConflicts?: () => void | Promise<void>;
  isRecheckingConflicts?: boolean;
}

export const NotificationsView: React.FC<Props> = ({
  conflicts,
  depletions,
  onResolveConflict,
  onRescheduleConflict,
  onConfirmDepletion,
  onDismissDepletion,
  onRecheckConflicts,
  isRecheckingConflicts = false,
}) => {
  const totalUnresolved = conflicts.length + depletions.length;
  const [activeTab, setActiveTab] = useState<string | null>('all');

  return (
    <Stack gap="md">
      {/* Page Header */}
      <Card withBorder radius="md" p="md">
        <Group justify="space-between" align="center">
          <Group gap="sm">
            <ThemeIcon color="red" size="lg" radius="xl" variant="light">
              <IconBell size={22} />
            </ThemeIcon>
            <Box>
              <Group gap="xs">
                <Text fw={800} size="lg">
                  Action Center & Notifications
                </Text>
                {totalUnresolved > 0 ? (
                  <Badge color="red" variant="filled" size="sm">
                    {totalUnresolved} Need Review
                  </Badge>
                ) : (
                  <Badge color="teal" variant="light" size="sm">
                    All Caught Up
                  </Badge>
                )}
              </Group>
              <Text size="xs" c="dimmed">
                Unresolved schedule clashes, pantry confirmation gate, and async extraction feeds
              </Text>
            </Box>
          </Group>
        </Group>
      </Card>

      {/* Empty State when everything is resolved */}
      {totalUnresolved === 0 && (
        <Card withBorder radius="md" p="xl" style={{ textAlign: 'center' }} bg="teal.0">
          <ThemeIcon color="teal" size={54} radius="xl" mx="auto" mb="sm" variant="light">
            <IconCheck size={32} />
          </ThemeIcon>
          <Text fw={700} size="md" c="teal.9">
            🎉 All Caught Up!
          </Text>
          <Text size="xs" c="dimmed" mt={4} maw={380} mx="auto">
            Zero pending conflicts and no pantry depletions waiting at the Confirmation Gate.
          </Text>
        </Card>
      )}

      {/* Tabs Filter */}
      {totalUnresolved > 0 && (
        <Tabs value={activeTab} onChange={setActiveTab} variant="pills" radius="xl">
          <Tabs.List mb="sm">
            <Tabs.Tab value="all">
              All Items ({totalUnresolved})
            </Tabs.Tab>
            <Tabs.Tab
              value="conflicts"
              rightSection={
                conflicts.length > 0 ? (
                  <Badge size="xs" color="red" variant="filled" circle>
                    {conflicts.length}
                  </Badge>
                ) : null
              }
            >
              Conflicts
            </Tabs.Tab>
            <Tabs.Tab
              value="depletions"
              rightSection={
                depletions.length > 0 ? (
                  <Badge size="xs" color="orange" variant="filled" circle>
                    {depletions.length}
                  </Badge>
                ) : null
              }
            >
              Pantry Gate
            </Tabs.Tab>
          </Tabs.List>

          {/* Tab 1: All Actionable Items */}
          <Tabs.Panel value="all">
            <Stack gap="md">
              {/* Conflicts Section */}
              {conflicts.length > 0 && (
                <Box>
                  <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb="xs">
                    ⚠️ Schedule Conflicts ({conflicts.length})
                  </Text>
                  <ConflictTriageCenter
                    conflicts={conflicts}
                    onResolve={onResolveConflict}
                    onReschedule={onRescheduleConflict}
                    onRecheck={onRecheckConflicts}
                    isRechecking={isRecheckingConflicts}
                  />
                </Box>
              )}

              {/* Pantry Depletions Section */}
              {depletions.length > 0 && (
                <Box>
                  <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb="xs">
                    🛒 Pantry Depletion Review ({depletions.length})
                  </Text>
                  <Card withBorder radius="md" p="md" bg="orange.0" style={{ borderColor: 'var(--mantine-color-orange-3)' }}>
                    <Group justify="space-between" mb="xs">
                      <Group gap="xs">
                        <ThemeIcon color="orange" size="md" radius="xl">
                          <IconShoppingCart size={18} />
                        </ThemeIcon>
                        <Box>
                          <Text fw={700} size="sm" c="orange.9">
                            Confirmation Gate
                          </Text>
                          <Text size="xs" c="dimmed">
                            Review AI burn-rate estimates before deducting from stock ledger
                          </Text>
                        </Box>
                      </Group>
                      <Badge color="orange" variant="light">Gate Approval</Badge>
                    </Group>

                    <Stack gap="xs" mt="sm">
                      {depletions.map((dep) => (
                        <Paper key={dep.id} p="xs" radius="sm" withBorder bg="white">
                          <Group justify="space-between">
                            <Box>
                              <Text size="sm" fw={700}>
                                {dep.product_name}
                              </Text>
                              <Text size="xs" c="orange.8" fw={600}>
                                Deduct {dep.proposed_deduction} {dep.unit}
                              </Text>
                              <Text size="10px" c="dimmed">
                                {dep.estimated_burn_rate}
                              </Text>
                            </Box>
                            <Group gap="xs">
                              <Button
                                size="compact-xs"
                                color="gray"
                                variant="subtle"
                                onClick={() => onDismissDepletion(dep.id)}
                                leftSection={<IconX size={14} />}
                              >
                                Dismiss
                              </Button>
                              <Button
                                size="compact-xs"
                                color="teal"
                                onClick={() => onConfirmDepletion(dep.id)}
                                leftSection={<IconCheck size={14} />}
                              >
                                Confirm
                              </Button>
                            </Group>
                          </Group>
                        </Paper>
                      ))}
                    </Stack>
                  </Card>
                </Box>
              )}

            </Stack>
          </Tabs.Panel>

          {/* Tab 2: Conflicts Only */}
          <Tabs.Panel value="conflicts">
            <ConflictTriageCenter
              conflicts={conflicts}
              onResolve={onResolveConflict}
              onReschedule={onRescheduleConflict}
              onRecheck={onRecheckConflicts}
              isRechecking={isRecheckingConflicts}
            />
          </Tabs.Panel>

          {/* Tab 3: Depletions Only */}
          <Tabs.Panel value="depletions">
            {depletions.length > 0 ? (
              <Stack gap="xs">
                {depletions.map((dep) => (
                  <Paper key={dep.id} p="sm" radius="md" withBorder bg="white">
                    <Group justify="space-between">
                      <Box>
                        <Text size="sm" fw={700}>
                          {dep.product_name}
                        </Text>
                        <Text size="xs" c="orange.8" fw={600}>
                          Deduct {dep.proposed_deduction} {dep.unit}
                        </Text>
                        <Text size="11px" c="dimmed">
                          {dep.estimated_burn_rate}
                        </Text>
                      </Box>
                      <Group gap="xs">
                        <Button
                          size="xs"
                          color="gray"
                          variant="subtle"
                          onClick={() => onDismissDepletion(dep.id)}
                          leftSection={<IconX size={14} />}
                        >
                          Dismiss
                        </Button>
                        <Button
                          size="xs"
                          color="teal"
                          onClick={() => onConfirmDepletion(dep.id)}
                          leftSection={<IconCheck size={14} />}
                        >
                          Confirm
                        </Button>
                      </Group>
                    </Group>
                  </Paper>
                ))}
              </Stack>
            ) : (
              <Paper p="md" withBorder radius="md" bg="gray.0" style={{ textAlign: 'center' }}>
                <Text size="xs" c="dimmed">No pantry depletions waiting at the Confirmation Gate.</Text>
              </Paper>
            )}
          </Tabs.Panel>
        </Tabs>
      )}
    </Stack>
  );
};
