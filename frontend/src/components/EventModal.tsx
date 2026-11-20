import React, { useEffect, useMemo, useState } from 'react';
import {
  Modal,
  Text,
  Badge,
  Group,
  Stack,
  Button,
  Paper,
  Box,
  SimpleGrid,
  Divider,
  Table,
  Checkbox,
  NumberInput,
  Select,
  Chip,
  ScrollArea,
  Alert,
  ActionIcon,
  Tooltip,
  TextInput,
  Textarea,
  Rating,
  Loader,
} from '@mantine/core';
import {
  IconShoppingCart,
  IconReceipt,
  IconCheck,
  IconClock,
  IconCalendar,
  IconMapPin,
  IconUser,
  IconBuildingStore,
  IconSparkles,
  IconX,
  IconFileCode,
  IconToolsKitchen2,
  IconTools,
  IconStethoscope,
  IconTrash,
  IconAlertTriangle,
  IconMan,
  IconWoman,
  IconMoodKid,
  IconUsers,
} from '@tabler/icons-react';
import { apiClient, ConflictCheckResult } from '../api/client';
import {
  EventItem,
  ReceiptJob,
  ProductItem,
  StoreItemMultiplier,
  ExtractedLineItem,
} from '../types';

interface Props {
  opened: boolean;
  event: EventItem | null;
  receiptJob?: ReceiptJob | null;
  products: ProductItem[];
  multipliers: StoreItemMultiplier[];
  onClose: () => void;
  onSaveEvent?: (updatedEvent: EventItem) => void;
  onConfirmReceiptJob?: (
    job: ReceiptJob,
    people: string[],
    updatePantry: boolean,
    updatedLineItems?: ExtractedLineItem[]
  ) => void;
  onUpsertMultiplier?: (store: string, item: string, multiplier: number, productId?: string) => void;
}

export const EventModal: React.FC<Props> = ({
  opened,
  event,
  receiptJob,
  products,
  multipliers,
  onClose,
  onSaveEvent,
  onConfirmReceiptJob,
  onUpsertMultiplier,
}) => {
  // Local editable event state
  const [title, setTitle] = useState('');
  const [selectedPeople, setSelectedPeople] = useState<string[]>(['Family']);
  const [notes, setNotes] = useState('');
  const [scheduledAt, setScheduledAt] = useState('');
  const [durationMinutes, setDurationMinutes] = useState(60);
  const [conflictWarning, setConflictWarning] = useState<ConflictCheckResult | null>(null);
  const [checkingConflict, setCheckingConflict] = useState(false);

  // Baseline snapshot when opening an existing event to trust pre-computed status until edited
  const [initialBaseline, setInitialBaseline] = useState<{
    scheduledAt: string;
    durationMinutes: number;
    people: string[];
    hasConflict: boolean;
    conflictReason?: string;
  } | null>(null);
  const [updatePantry, setUpdatePantry] = useState(true);
  const [lineItems, setLineItems] = useState<ExtractedLineItem[]>([]);
  const [subtotal, setSubtotal] = useState<number>(0);
  const [tax, setTax] = useState<number>(0);
  const [total, setTotal] = useState<number>(0);

  // Initialize modal state when opened or event/job changes
  useEffect(() => {
    if (!opened) {
      setInitialBaseline(null);
      setConflictWarning(null);
      setCheckingConflict(false);
      return;
    }

    if (receiptJob?.result) {
      // Configured from receipt job (pre-confirmation)
      const res = receiptJob.result;
      const storeName = res.merchant_name || 'Costco Wholesale';
      setTitle(storeName);
      setSelectedPeople(['Family']);
      setNotes(`Ingested via Approach 2 from ${receiptJob.filename}`);
      setUpdatePantry(true);
      setSubtotal(res.subtotal ?? res.total_amount);
      setTax(res.tax_amount ?? 0);
      setTotal(res.total_amount);

      // Pre-link line items from multipliers lookup
      const initializedItems: ExtractedLineItem[] = (res.line_items || []).map((it) => {
        const matched =
          multipliers.find(
            (m) =>
              m.store.toLowerCase().includes(storeName.toLowerCase().slice(0, 6)) &&
              m.item.toLowerCase() === it.name.toLowerCase()
          ) ||
          multipliers.find(
            (m) => m.item.toLowerCase() === it.name.toLowerCase()
          );

        if (!it.grocy_product_id && matched?.product_id) {
          return {
            ...it,
            grocy_product_id: matched.product_id,
            grocy_product_name: matched.product_name || it.name,
            unit_multiplier: matched.multiplier ?? 1.0,
            to_create_stock: false,
          };
        }

        const defaultMult = matched?.multiplier ?? it.unit_multiplier ?? 1.0;
        return {
          ...it,
          to_create_stock: it.to_create_stock ?? (!it.grocy_product_id && it.total_price >= 0),
          unit_multiplier: it.unit_multiplier ?? defaultMult,
        };
      });

      setLineItems(initializedItems);
      setInitialBaseline(null);
    } else if (event) {
      // Configured from an existing ledger event
      setTitle(event.title);
      const initPeople = event.people_involved || ['Family'];
      setSelectedPeople(initPeople);
      setNotes(event.description || event.notes || '');
      setUpdatePantry(event.shopping_details?.pantry_updated ?? true);

      let initScheduled = '';
      if (event.scheduled_at) {
        try {
          const d = new Date(event.scheduled_at);
          const y = d.getFullYear();
          const m = String(d.getMonth() + 1).padStart(2, '0');
          const day = String(d.getDate()).padStart(2, '0');
          const h = String(d.getHours()).padStart(2, '0');
          const min = String(d.getMinutes()).padStart(2, '0');
          initScheduled = `${y}-${m}-${day}T${h}:${min}`;
        } catch {
          initScheduled = '';
        }
      } else {
        initScheduled = '';
      }
      const initDuration = event.duration_minutes || 60;
      setScheduledAt(initScheduled);
      setDurationMinutes(initDuration);
      setConflictWarning(null);
      setCheckingConflict(false);

      // Record exact initial baseline to detect actual modifications
      setInitialBaseline({
        scheduledAt: initScheduled,
        durationMinutes: initDuration,
        people: [...initPeople].sort(),
        hasConflict: !!event.has_conflict,
        conflictReason: event.conflict_reason,
      });

      const existingAmt =
        event.dining_details?.total_amount ??
        event.shopping_details?.total_amount ??
        (event as any).total_amount ??
        0;

      if (event.shopping_details) {
        setTotal(existingAmt);
        setSubtotal(existingAmt);
        setTax(0);

        const sItems = event.shopping_details.line_items || [];
        setLineItems(
          sItems.map((it: any) => ({
            name: it.name || it.product_name || 'Item',
            quantity: it.quantity || 1,
            unit: it.unit || 'unit',
            unit_price: it.unit_price || 0,
            total_price: it.total_price || (it.quantity || 1) * (it.unit_price || 0),
            grocy_product_id: it.grocy_product_id,
            grocy_product_name: it.grocy_product_name,
            unit_multiplier: it.unit_multiplier || 1.0,
            to_create_stock: false,
          }))
        );
      } else {
        setLineItems([]);
        setTotal(existingAmt);
        setSubtotal(existingAmt);
        setTax(0);
      }
    }
  }, [opened, event, receiptJob, multipliers]);

  // Lazy load full event if opened with a stub event object missing details
  useEffect(() => {
    if (opened && event?.id && !event.shopping_details && !event.dining_details && !(event as any).total_amount) {
      apiClient
        .getEvent(event.id)
        .then((fullEvt) => {
          if (fullEvt) {
            setTitle(fullEvt.title);
            if (fullEvt.scheduled_at) {
              try {
                const d = new Date(fullEvt.scheduled_at);
                const y = d.getFullYear();
                const m = String(d.getMonth() + 1).padStart(2, '0');
                const day = String(d.getDate()).padStart(2, '0');
                const h = String(d.getHours()).padStart(2, '0');
                const min = String(d.getMinutes()).padStart(2, '0');
                setScheduledAt(`${y}-${m}-${day}T${h}:${min}`);
              } catch {}
            }
            const amt =
              fullEvt.dining_details?.total_amount ??
              fullEvt.shopping_details?.total_amount ??
              (fullEvt as any).total_amount ??
              0;
            if (amt > 0) {
              setTotal(amt);
              setSubtotal(amt);
            }
            if (fullEvt.people_involved && fullEvt.people_involved.length > 0) {
              setSelectedPeople(fullEvt.people_involved);
            }
            if (fullEvt.description || fullEvt.notes) {
              setNotes(fullEvt.description || fullEvt.notes || '');
            }
          }
        })
        .catch(() => {});
    }
  }, [opened, event?.id]);

  // Determine if date, duration, or people actually changed compared to initial baseline
  const isTimingOrPeopleChanged = useMemo(() => {
    if (!initialBaseline) return true; // New / receipt item without baseline
    if (scheduledAt !== initialBaseline.scheduledAt) return true;
    if (durationMinutes !== initialBaseline.durationMinutes) return true;
    const currentPeopleSorted = [...selectedPeople].sort().join(',');
    const initialPeopleSorted = initialBaseline.people.join(',');
    if (currentPeopleSorted !== initialPeopleSorted) return true;
    return false;
  }, [scheduledAt, durationMinutes, selectedPeople, initialBaseline]);

  useEffect(() => {
    if (!opened || !scheduledAt) {
      setConflictWarning(null);
      setCheckingConflict(false);
      return;
    }

    // When opening an existing event without any editing, trust pre-computed is_conflict!
    if (initialBaseline && !isTimingOrPeopleChanged) {
      setConflictWarning(null);
      setCheckingConflict(false);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        const parsedDate = new Date(scheduledAt);
        if (isNaN(parsedDate.getTime())) {
          setCheckingConflict(false);
          return;
        }
        setCheckingConflict(true);
        const res = await apiClient.checkConflict({
          scheduled_at: parsedDate.toISOString(),
          duration_minutes: durationMinutes,
          title: title.trim() || event?.title || 'Event',
          people_involved: selectedPeople,
          place_id: event?.place_id,
          event_id: event?.id,
        });
        setConflictWarning(res);
      } catch (err) {
        console.warn('Conflict check request failed:', err);
      } finally {
        setCheckingConflict(false);
      }
    }, 350);

    return () => clearTimeout(timer);
  }, [opened, scheduledAt, durationMinutes, selectedPeople, title, event?.place_id, event?.id, initialBaseline, isTimingOrPeopleChanged]);

  if (!opened || (!event && !receiptJob)) return null;

  const eventType = event?.event_type || 'SHOPPING';
  const isShopping = eventType === 'SHOPPING';
  const isDining = eventType === 'DINING';
  const isConfirmingReceipt = !!receiptJob && !event?.id;

  // Place info
  const placeName =
    receiptJob?.result?.merchant_name ||
    event?.place_name ||
    event?.shopping_details?.store_name ||
    'Costco Wholesale';
  const placeAddress = receiptJob?.result?.merchant_address || event?.place_address;
  const placeId = receiptJob?.result?.place_id || event?.place_id;
  const lat = event?.latitude;
  const lng = event?.longitude;
  const displayTime =
    receiptJob?.result?.transaction_time ||
    event?.completed_at ||
    event?.scheduled_at ||
    new Date().toISOString();

  // Handlers for shopping line items
  const handleToggleCreateStock = (index: number, checked: boolean) => {
    setLineItems((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], to_create_stock: checked };
      return copy;
    });
  };

  const handleUpdateItemMultiplier = (index: number, multiplier: number) => {
    setLineItems((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], unit_multiplier: multiplier };
      return copy;
    });
  };

  const handleLinkExistingProduct = (index: number, productId: string) => {
    const prod = products.find((p) => p.id === productId);
    if (!prod) return;
    setLineItems((prev) => {
      const copy = [...prev];
      copy[index] = {
        ...copy[index],
        grocy_product_id: prod.id,
        grocy_product_name: prod.name,
        unit_multiplier: prod.unit_multiplier || copy[index].unit_multiplier || 1.0,
        to_create_stock: false,
      };
      return copy;
    });
  };

  const handleClearProductLink = (index: number) => {
    setLineItems((prev) => {
      const copy = [...prev];
      copy[index] = {
        ...copy[index],
        grocy_product_id: undefined,
        grocy_product_name: undefined,
        to_create_stock: true,
        unit_multiplier: 1.0,
      };
      return copy;
    });
  };

  // Submission handler
  const handleSubmit = () => {
    if (isConfirmingReceipt && receiptJob && onConfirmReceiptJob) {
      onConfirmReceiptJob(receiptJob, selectedPeople, updatePantry, lineItems);
    } else if (event && onSaveEvent) {
      const updated: EventItem = {
        ...event,
        title,
        people_involved: selectedPeople,
        description: notes,
        scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : event.scheduled_at,
        duration_minutes: durationMinutes,
        ...(isShopping
          ? {
              shopping_details: {
                ...event.shopping_details,
                store_name: placeName,
                total_amount: total,
                pantry_updated: updatePantry,
                line_items: lineItems,
              },
            }
          : {}),
      };
      onSaveEvent(updated);
    }
    onClose();
  };

  const getHeaderIcon = () => {
    switch (eventType) {
      case 'SHOPPING':
        return <IconShoppingCart size={22} color="var(--mantine-color-teal-7)" />;
      case 'DINING':
        return <IconToolsKitchen2 size={22} color="var(--mantine-color-orange-7)" />;
      case 'MAINTENANCE':
        return <IconTools size={22} color="var(--mantine-color-blue-7)" />;
      case 'MEDICAL':
        return <IconStethoscope size={22} color="var(--mantine-color-red-7)" />;
      default:
        return <IconCalendar size={22} color="var(--mantine-color-indigo-7)" />;
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      closeOnClickOutside={false}
      closeOnEscape={false}
      title={
        <Group gap="xs">
          {getHeaderIcon()}
          <Box>
            <Group gap="xs" align="center">
              <Text fw={700} size="md">
                {isConfirmingReceipt ? 'Review & Confirm Shopping Event' : 'Event Details'}
              </Text>
              <Badge color="blue" size="xs" variant="light">
                {eventType}
              </Badge>
              {isConfirmingReceipt ? (
                <Badge color="yellow" size="xs" variant="filled">
                  Pending Confirmation
                </Badge>
              ) : (
                <Badge color="teal" size="xs" variant="light">
                  ✓ Recorded on Ledger
                </Badge>
              )}
            </Group>
          </Box>
        </Group>
      }
      size="lg"
      radius="md"
    >
      <Stack gap="md">
        {isConfirmingReceipt && (
          <Alert color="teal" variant="light" p="xs">
            <Text size="xs">
              Approach 2 CAS background parser completed. Review verified merchant, line items, and packaging multipliers before committing this event to the ledger.
            </Text>
          </Alert>
        )}

        {/* 1. Event & Place Grounding Header */}
        <Paper p="sm" withBorder radius="sm" bg="gray.0">
          <Group justify="space-between" align="flex-start">
            <Box style={{ flex: 1 }}>
              <TextInput
                label="Event Title"
                value={title}
                onChange={(e) => setTitle(e.currentTarget.value)}
                size="xs"
                fw={700}
                placeholder="Store or event title..."
                mb={4}
              />

              {placeAddress && (
                <Group gap={4} mt={2}>
                  <IconMapPin size={14} color="var(--mantine-color-dimmed)" />
                  <Text size="xs" c="dimmed">
                    {placeAddress}
                  </Text>
                </Group>
              )}
            </Box>

            <Group gap="xs">
              {placeId && (
                <Badge color="blue" variant="light" size="sm">
                  📍 {placeId}
                </Badge>
              )}
              {lat !== undefined && lng !== undefined && (
                <Badge color="gray" variant="outline" size="sm">
                  🌐 {lat.toFixed(4)}, {lng.toFixed(4)}
                </Badge>
              )}
            </Group>
          </Group>

          <Divider my="xs" />

          {/* Temporal & People Metadata */}
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
            <Group gap={6}>
              <IconClock size={15} color="var(--mantine-color-dimmed)" />
              <Text size="xs" c="dimmed">
                Time: <strong>{new Date(displayTime).toLocaleString()}</strong>
              </Text>
            </Group>

            {receiptJob?.filename && (
              <Group gap={6}>
                <IconFileCode size={15} color="var(--mantine-color-teal-7)" />
                <Text size="xs" c="dimmed" truncate>
                  Source: <strong>{receiptJob.filename}</strong>
                </Text>
              </Group>
            )}
          </SimpleGrid>
        </Paper>

        {/* 2. Shopping Receipt View (Financials & Extracted Line Items) */}
        {isShopping && (
          <Stack gap="sm">
            {/* Financial Summary */}
            <SimpleGrid cols={3} spacing="xs">
              <Paper p="xs" withBorder radius="sm" ta="center">
                <Text size="10px" c="dimmed">SUBTOTAL</Text>
                <Text fw={700} size="sm">
                  ${subtotal.toFixed(2)}
                </Text>
              </Paper>
              <Paper p="xs" withBorder radius="sm" ta="center">
                <Text size="10px" c="dimmed">TAX</Text>
                <Text fw={700} size="sm">
                  ${tax.toFixed(2)}
                </Text>
              </Paper>
              <Paper p="xs" withBorder radius="sm" ta="center" bg="teal.0">
                <Text size="10px" c="teal.9" fw={700}>TOTAL PAID</Text>
                <Text fw={800} size="md" c="teal.9">
                  ${(total || event?.shopping_details?.total_amount || event?.dining_details?.total_amount || (event as any)?.total_amount || 0).toFixed(2)}
                </Text>
              </Paper>
            </SimpleGrid>

            {/* Extracted Line Items Table */}
            {lineItems.length > 0 && (
              <Box>
                <Group justify="space-between" mb={4}>
                  <Text fw={700} size="xs" c="dimmed">
                    ITEMIZED RECEIPT ITEMS ({lineItems.length})
                  </Text>
                  <Text size="10px" c="dimmed">
                    Links to pantry stock & packaging multipliers
                  </Text>
                </Group>

                <ScrollArea.Autosize mah={240}>
                  <Table striped highlightOnHover withTableBorder withColumnBorders fz="xs">
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Item</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>Qty</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>Price</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>Total</Table.Th>
                        <Table.Th>Pantry Link & Multiplier</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {lineItems.map((item, idx) => (
                        <Table.Tr key={idx}>
                          <Table.Td fw={500}>{item.name}</Table.Td>
                          <Table.Td style={{ textAlign: 'right' }}>
                            {item.quantity} {item.unit || ''}
                          </Table.Td>
                          <Table.Td style={{ textAlign: 'right' }}>
                            ${item.unit_price.toFixed(2)}
                          </Table.Td>
                          <Table.Td
                            style={{
                              textAlign: 'right',
                              color: item.total_price < 0 ? 'var(--mantine-color-green-7)' : undefined,
                              fontWeight: 600,
                            }}
                          >
                            ${item.total_price.toFixed(2)}
                          </Table.Td>
                          <Table.Td>
                            {item.grocy_product_id ? (
                              <Group gap={4} wrap="nowrap" align="center">
                                <Badge color="green" size="xs" variant="filled">
                                  Grocy: {item.grocy_product_name || item.grocy_product_id}
                                </Badge>
                                {item.unit_multiplier && item.unit_multiplier > 1 && (
                                  <Badge color="teal" size="xs" variant="light">
                                    ×{item.unit_multiplier} = +{((item.quantity || 1) * item.unit_multiplier).toFixed(0)} {item.unit || 'units'}
                                  </Badge>
                                )}
                                <Tooltip label="Change / unlink product" withArrow>
                                  <ActionIcon
                                    size="xs"
                                    color="gray"
                                    variant="subtle"
                                    onClick={() => handleClearProductLink(idx)}
                                    title="Unlink"
                                  >
                                    <IconX size={13} />
                                  </ActionIcon>
                                </Tooltip>
                              </Group>
                            ) : item.total_price < 0 ? (
                              <Badge color="gray" size="xs" variant="outline">
                                Instant Discount
                              </Badge>
                            ) : (
                              <Stack gap={4}>
                                <Group gap="xs" wrap="nowrap" align="center">
                                  <Checkbox
                                    label="Create stock product"
                                    size="xs"
                                    color="teal"
                                    checked={item.to_create_stock !== false}
                                    onChange={(e) => handleToggleCreateStock(idx, e.currentTarget.checked)}
                                  />
                                  {item.to_create_stock !== false && (
                                    <Group gap={4} wrap="nowrap" align="center">
                                      <Text size="xs" c="dimmed">×</Text>
                                      <NumberInput
                                        size="xs"
                                        w={60}
                                        min={0.1}
                                        step={1}
                                        value={item.unit_multiplier ?? 1}
                                        onChange={(val) => handleUpdateItemMultiplier(idx, typeof val === 'number' ? val : 1)}
                                      />
                                      <Badge color="teal" size="xs" variant="light">
                                        +{((item.quantity || 1) * (item.unit_multiplier || 1)).toFixed(0)} units
                                      </Badge>
                                    </Group>
                                  )}
                                </Group>
                                {item.to_create_stock === false && products && products.length > 0 && (
                                  <Group gap={4} wrap="nowrap" align="center">
                                    <Select
                                      placeholder="Or link to existing product..."
                                      size="xs"
                                      w={200}
                                      clearable
                                      searchable
                                      data={products.map((p) => ({ value: p.id, label: p.name }))}
                                      onChange={(val) => val && handleLinkExistingProduct(idx, val)}
                                    />
                                    <Text size="xs" c="dimmed">×</Text>
                                    <NumberInput
                                      size="xs"
                                      w={55}
                                      min={0.1}
                                      step={1}
                                      value={item.unit_multiplier ?? 1}
                                      onChange={(val) => handleUpdateItemMultiplier(idx, typeof val === 'number' ? val : 1)}
                                    />
                                  </Group>
                                )}
                              </Stack>
                            )}
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </ScrollArea.Autosize>
              </Box>
            )}

            {/* Pantry Stock Replenishment Option */}
            <Checkbox
              label="Update pantry inventory stock & cross off matched shopping list items"
              description="Automatically restock matched items in pantry catalog with packaging multiplier"
              checked={updatePantry}
              onChange={(e) => setUpdatePantry(e.currentTarget.checked)}
              size="xs"
              color="teal"
            />
          </Stack>
        )}

        {/* 3. Dining Details View */}
        {isDining && (
          <Paper p="sm" withBorder radius="sm">
            <Group justify="space-between" mb="xs">
              <Text size="xs" fw={700} c="dimmed">
                DINING SUMMARY
              </Text>
              <Rating value={event?.dining_details?.rating || 5} readOnly size="sm" />
            </Group>
            <Text size="sm" fw={700}>
              Total Paid: ${(event?.dining_details?.total_amount || event?.shopping_details?.total_amount || (event as any)?.total_amount || total || 0).toFixed(2)}
            </Text>
          </Paper>
        )}

        {/* Schedule & Timing (Editable for Scheduled Events) */}
        {scheduledAt && (
          <Paper p="xs" withBorder radius="sm">
            <Group justify="space-between" align="center" mb={6}>
              <Text fw={700} size="xs" c="dimmed">
                SCHEDULE & TIMING
              </Text>

              {/* Mobile Compact Conflict Status Icon with Tooltip */}
              {checkingConflict ? (
                <Group gap={4}>
                  <Loader size={12} color="gray" />
                  <Text size="10px" c="dimmed">Checking...</Text>
                </Group>
              ) : isTimingOrPeopleChanged && conflictWarning && conflictWarning.has_conflict ? (
                <Tooltip
                  label={conflictWarning.conflicts.map((c) => c.title).join(' • ') || 'Schedule conflict detected'}
                  multiline
                  w={220}
                  withArrow
                >
                  <Badge color="red" size="xs" variant="filled" leftSection={<IconAlertTriangle size={11} />} style={{ cursor: 'pointer' }}>
                    Conflict
                  </Badge>
                </Tooltip>
              ) : isTimingOrPeopleChanged && conflictWarning && !conflictWarning.has_conflict ? (
                <Tooltip label="Time slot & attendees clear" withArrow>
                  <Badge color="teal" size="xs" variant="light" leftSection={<IconCheck size={11} />} style={{ cursor: 'pointer' }}>
                    Clear
                  </Badge>
                </Tooltip>
              ) : initialBaseline?.hasConflict ? (
                <Tooltip label={initialBaseline.conflictReason || 'Pre-computed conflict on schedule'} multiline w={220} withArrow>
                  <Badge color="red" size="xs" variant="light" leftSection={<IconAlertTriangle size={11} />} style={{ cursor: 'pointer' }}>
                    Conflict
                  </Badge>
                </Tooltip>
              ) : (
                <Tooltip label="No conflicts on calendar" withArrow>
                  <Badge color="teal" size="xs" variant="subtle" leftSection={<IconCheck size={11} />}>
                    Clear
                  </Badge>
                </Tooltip>
              )}
            </Group>

            <Group grow align="flex-start">
              <TextInput
                label="Scheduled Time"
                type="datetime-local"
                size="xs"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.currentTarget.value)}
                leftSection={<IconClock size={14} />}
              />
              <NumberInput
                label="Duration (minutes)"
                size="xs"
                min={15}
                step={15}
                value={durationMinutes}
                onChange={(v) => setDurationMinutes(typeof v === 'number' ? v : 60)}
              />
            </Group>

            {/* Short 1-line note if conflict detected */}
            {((isTimingOrPeopleChanged && conflictWarning?.has_conflict) || (!isTimingOrPeopleChanged && initialBaseline?.hasConflict)) && (
              <Text size="11px" c="red.8" fw={500} mt={6} truncate>
                ⚠️ {conflictWarning?.conflicts[0]?.title || initialBaseline?.conflictReason || 'Schedule conflict detected'}
              </Text>
            )}
          </Paper>
        )}

        {/* 4. Extra Information from Event: Who Was There */}
        <Box>
          <Text fw={700} size="xs" c="dimmed" mb={4}>
            WHO WAS THERE
          </Text>
          <Chip.Group multiple value={selectedPeople} onChange={setSelectedPeople}>
            <Group gap="xs">
              <Chip value="Family" size="xs">
                <Group gap={4} wrap="nowrap">
                  <IconUsers size={12} color="#7950f2" />
                  <span>Family</span>
                </Group>
              </Chip>
              <Chip value="Dad" size="xs">
                <Group gap={4} wrap="nowrap">
                  <IconMan size={12} color="#1c7ed6" />
                  <span>Dad</span>
                </Group>
              </Chip>
              <Chip value="Mom" size="xs">
                <Group gap={4} wrap="nowrap">
                  <IconWoman size={12} color="#e64980" />
                  <span>Mom</span>
                </Group>
              </Chip>
              <Chip value="Marcus" size="xs">
                <Group gap={4} wrap="nowrap">
                  <IconMoodKid size={12} color="#12b886" />
                  <span>Marcus</span>
                </Group>
              </Chip>
            </Group>
          </Chip.Group>
        </Box>

        {/* 5. Extra Information from Event: Notes & Context */}
        <Textarea
          label="Event Notes / Receipt Context"
          value={notes}
          onChange={(e) => setNotes(e.currentTarget.value)}
          size="xs"
          placeholder="Trip context, receipt details, or notes..."
          minRows={2}
        />

        <Divider />

        {/* 6. Modal Actions */}
        <Group justify="flex-end" gap="sm">
          {isConfirmingReceipt ? (
            <Button
              color="teal"
              fullWidth
              leftSection={<IconCheck size={16} />}
              onClick={handleSubmit}
            >
              Confirm & Log
            </Button>
          ) : (
            <Button
              color="blue"
              fullWidth
              leftSection={<IconCheck size={16} />}
              onClick={handleSubmit}
            >
              Save Changes
            </Button>
          )}
        </Group>
      </Stack>
    </Modal>
  );
};
