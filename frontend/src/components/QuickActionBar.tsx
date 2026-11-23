import React, { useState, useRef } from 'react';
import {
  Card,
  Group,
  Button,
  Modal,
  Drawer,
  Text,
  TextInput,
  Textarea,
  Select,
  SimpleGrid,
  Badge,
  Stack,
  Chip,
  Box,
  Paper,
  Rating,
  ThemeIcon,
  Divider,
  SegmentedControl,
  Checkbox,
  FileButton,
} from '@mantine/core';
import {
  IconPlus,
  IconDots,
  IconCheck,
  IconCamera,
  IconUpload,
  IconClock,
  IconUser,
  IconMapPin,
  IconReceipt,
  IconCar,
  IconTools,
  IconStethoscope,
  IconSwimming,
  IconSparkles,
  IconMan,
  IconWoman,
  IconMoodKid,
} from '@tabler/icons-react';
import { QuickTemplate, EventItem, SnapIntent } from '../types';
import { SimpleQuickAddModal } from './SimpleQuickAddModal';

interface Props {
  templates: QuickTemplate[];
  onSaveQuickEvent: (event: Partial<EventItem>) => void;
  onSnapReceipt: (intent: SnapIntent, details?: Partial<EventItem>) => void;
  onUploadReceipt?: (file: File) => Promise<void> | void;
}

export const QuickActionBar: React.FC<Props> = ({
  templates,
  onSaveQuickEvent,
  onSnapReceipt,
  onUploadReceipt,
}) => {
  const [drawerOpened, setDrawerOpened] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<QuickTemplate | null>(null);
  const [quickModalOpened, setQuickModalOpened] = useState(false);
  const [smartIntakeOpened, setSmartIntakeOpened] = useState(false);
  const [simpleModalOpened, setSimpleModalOpened] = useState(false);
  const [simpleTemplate, setSimpleTemplate] = useState<QuickTemplate | null>(null);
  const [isUploadingReceipt, setIsUploadingReceipt] = useState(false);

  const handleFileChosen = async (file: File | null) => {
    if (!file || !onUploadReceipt) return;
    setIsUploadingReceipt(true);
    try {
      await onUploadReceipt(file);
    } finally {
      setIsUploadingReceipt(false);
    }
  };

  // Helper to get formatted local datetime string: YYYY-MM-DDTHH:mm
  const formatDatetimeLocal = (date: Date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${minutes}`;
  };

  // Helper to compute formatted end time string: HH:mm AM/PM
  const computeEndTimeDisplay = (startIsoOrLocal: string, durationMinutes: number) => {
    try {
      const start = new Date(startIsoOrLocal);
      if (isNaN(start.getTime())) return '';
      const end = new Date(start.getTime() + durationMinutes * 60000);
      return end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  };

  // ── Form State for Standard Quick Modal (Diaper, Routine) ──────────────
  const [title, setTitle] = useState('');
  const [person, setPerson] = useState('Marcus');
  const [startTime, setStartTime] = useState(formatDatetimeLocal(new Date()));
  const [durationMinutes, setDurationMinutes] = useState(30);
  const [location, setLocation] = useState('Home (100 Main St, Cranberry Twp, PA)');
  const [description, setDescription] = useState('');
  const [diaperTag, setDiaperTag] = useState('Poop');

  // ── Form State for Unified Smart Intake Modal ────────────────────────────
  const [snapIntent, setSnapIntent] = useState<SnapIntent>('DINING');
  const [receiptImageName, setReceiptImageName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [snapTitle, setSnapTitle] = useState('Dinner');
  const [snapPeople, setSnapPeople] = useState<string[]>(['Dad', 'Mom', 'Marcus']);
  const [snapStartTime, setSnapStartTime] = useState(formatDatetimeLocal(new Date(Date.now() - 60 * 60000)));
  const [snapDurationMinutes, setSnapDurationMinutes] = useState(60);
  const [snapLocation, setSnapLocation] = useState('Current Location (Nearby)');
  const [snapNotes, setSnapNotes] = useState('');

  // Intent Specific Fields
  const [diningRating, setDiningRating] = useState(5);

  const [storePantryRestock, setStorePantryRestock] = useState(true);

  const [maintService, setMaintService] = useState('Oil Change & Tire Rotation');

  const [medSpecialty, setMedSpecialty] = useState('Pediatrician');
  const [medPrescription, setMedPrescription] = useState('Checkup & Amoxicillin prescription');

  // Open the Unified Smart Intake Modal with specified intent
  const openSmartIntake = (intent: SnapIntent, defaultTitle?: string) => {
    const now = new Date();
    const durationMins = intent === 'TRAVEL' || intent === 'CUSTOM' ? 30 : 60;
    const pastStart = new Date(now.getTime() - durationMins * 60000);

    setSnapIntent(intent);
    setReceiptImageName(null);
    setSnapStartTime(formatDatetimeLocal(pastStart));
    setSnapDurationMinutes(durationMins);
    setSnapLocation('Current Location (Nearby)');
    setSnapNotes('');

    if (intent === 'DINING') {
      setSnapTitle(defaultTitle || 'Dinner');
      setSnapPeople(['Dad', 'Mom', 'Marcus']);
    } else if (intent === 'SHOPPING') {
      setSnapTitle(defaultTitle || 'Costco Wholesale Restock');
      setSnapPeople(['Dad']);
      setStorePantryRestock(true);
    } else if (intent === 'MAINTENANCE') {
      setSnapTitle(defaultTitle || 'Honda Odyssey Service');
      setSnapPeople(['Dad']);
    } else if (intent === 'MEDICAL') {
      setSnapTitle(defaultTitle || 'Doctor Visit for Marcus');
      setSnapPeople(['Mom', 'Marcus']);
    } else {
      setSnapTitle(defaultTitle || 'Receipt Expense');
      setSnapPeople(['Family']);
    }

    setSmartIntakeOpened(true);
  };

  const handleOpenTemplate = (tpl: QuickTemplate) => {
    if (tpl.modal_type === 'smart_intake' || tpl.id === 'tpl_dining' || tpl.id === 'tpl_grocery' || tpl.id === 'tpl_oil') {
      if (tpl.id === 'tpl_dining') {
        openSmartIntake('DINING', 'Dinner');
      } else if (tpl.id === 'tpl_grocery') {
        openSmartIntake('SHOPPING', 'Grocery Restock');
      } else if (tpl.id === 'tpl_oil') {
        openSmartIntake('MAINTENANCE', 'Honda Odyssey Maintenance');
      } else {
        openSmartIntake(tpl.default_category as SnapIntent, tpl.name);
      }
      return;
    }

    if (tpl.modal_type === 'simple' || tpl.id === 'tpl_diaper' || tpl.id === 'tpl_poop' || tpl.id === 'tpl_swimming' || tpl.id === 'tpl_pool') {
      setSimpleTemplate(tpl);
      setDrawerOpened(false);
      setSimpleModalOpened(true);
      return;
    }

    const now = new Date();
    setSelectedTemplate(tpl);
    setTitle(tpl.name);
    setPerson(tpl.default_person);
    setDescription(tpl.default_description);
    setStartTime(formatDatetimeLocal(now));
    setDurationMinutes(tpl.default_duration_minutes || 30);
    setLocation('Home (100 Main St, Cranberry Twp, PA)');
    setDrawerOpened(false);
    setQuickModalOpened(true);
  };

  const handleIntakeDurationChange = (mins: number) => {
    setSnapDurationMinutes(mins);
    const now = new Date();
    setSnapStartTime(formatDatetimeLocal(new Date(now.getTime() - mins * 60000)));
  };

  const handlePhotoCaptured = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setReceiptImageName(e.target.files[0].name);
    }
  };

  const simulateCameraSnap = () => {
    setReceiptImageName('receipt_camera_snap.jpg');
  };

  const handleSaveQuickEvent = () => {
    const finalDesc = selectedTemplate?.id === 'tpl_diaper'
      ? `My son pooped (${diaperTag})${description ? ' - ' + description : ''}`
      : description;

    const startDate = new Date(startTime);
    const computedEnd = !isNaN(startDate.getTime())
      ? new Date(startDate.getTime() + durationMinutes * 60000).toISOString()
      : undefined;

    onSaveQuickEvent({
      title: title || selectedTemplate?.name || 'Quick Event',
      event_type: selectedTemplate?.default_category || 'CUSTOM',
      scheduled_at: startTime,
      scheduled_end_at: computedEnd,
      completed_at: computedEnd || new Date().toISOString(),
      people_involved: [person],
      description: finalDesc,
      place_name: location,
      latitude: 40.6865,
      longitude: -80.1081,
    });

    setQuickModalOpened(false);
  };

  const handleSaveSmartIntake = () => {
    const startDate = new Date(snapStartTime);
    const computedEnd = !isNaN(startDate.getTime())
      ? new Date(startDate.getTime() + snapDurationMinutes * 60000).toISOString()
      : new Date().toISOString();

    const eventDetails: Partial<EventItem> = {
      title: snapTitle,
      event_type: snapIntent === 'MEDICAL' ? 'CUSTOM' : snapIntent,
      completed_at: computedEnd,
      scheduled_at: snapStartTime,
      scheduled_end_at: computedEnd,
      place_name: snapLocation,
      people_involved: snapPeople,
      description: snapNotes,
      latitude: 40.6865,
      longitude: -80.1081,
    };

    if (snapIntent === 'DINING') {
      eventDetails.dining_details = {
        rating: diningRating,
      };
    } else if (snapIntent === 'SHOPPING') {
      eventDetails.shopping_details = {
        pantry_updated: storePantryRestock,
      };
    } else if (snapIntent === 'MAINTENANCE') {
      eventDetails.maintenance_details = {
        service_type: maintService,
      };
    }

    onSnapReceipt(snapIntent, eventDetails);
    setSmartIntakeOpened(false);
  };

  // Mobile quick action presets: Marcus Pooped, Dining, Shopping, Dog walk, Swimming
  const TARGET_PRESET_IDS = ['tpl_diaper', 'tpl_dining', 'tpl_grocery', 'tpl_dog', 'tpl_swimming'];

  const defaultPresets: QuickTemplate[] = [
    {
      id: 'tpl_diaper',
      name: 'Marcus Pooped',
      icon: '💩',
      default_category: 'CUSTOM',
      default_person: 'Marcus',
      default_duration_minutes: 15,
      default_description: 'Marcus pooped',
      pinned: true,
      modal_type: 'simple',
    },
    {
      id: 'tpl_dining',
      name: 'Dining',
      icon: '🍽️',
      default_category: 'DINING',
      default_person: 'Family',
      default_duration_minutes: 60,
      default_description: 'Dinner at restaurant',
      pinned: true,
      modal_type: 'smart_intake',
    },
    {
      id: 'tpl_grocery',
      name: 'Shopping',
      icon: '🛒',
      default_category: 'SHOPPING',
      default_person: 'Dad',
      default_duration_minutes: 45,
      default_description: 'Pantry restocking run',
      pinned: true,
      modal_type: 'smart_intake',
    },
    {
      id: 'tpl_dog',
      name: 'Dog walk',
      icon: '🐕',
      default_category: 'CUSTOM',
      default_person: 'Dad',
      default_duration_minutes: 30,
      default_description: 'Neighborhood dog walk',
      pinned: true,
      modal_type: 'simple',
    },
    {
      id: 'tpl_swimming',
      name: 'Swimming',
      icon: '🏊',
      default_category: 'CUSTOM',
      default_person: 'Marcus',
      default_people: ['Marcus', 'Dad'],
      default_duration_minutes: 60,
      default_description: 'Swimming at Rose E. Schneider Family YMCA (Warm Water Pool)',
      pinned: true,
      modal_type: 'simple',
      default_place: 'Rose E. Schneider Family YMCA',
      default_place_id: 'pl_ymca',
      default_studio: 'Warm Water Pool',
      default_coords: { latitude: 40.7021, longitude: -80.1245 },
    },
  ];

  const presets = TARGET_PRESET_IDS.map(
    (id) => templates.find((t) => t.id === id) || defaultPresets.find((d) => d.id === id)!
  );

  return (
    <>
      <Card withBorder radius="md" p="xs" bg="gray.0">
        <Group justify="space-between" align="center" mb={6} wrap="wrap" gap="xs">
          <Text size="xs" fw={700} c="dimmed" tt="uppercase">
            ⚡ Quick Actions
          </Text>
          <Group gap={6}>
            <FileButton
              accept="image/*"
              capture="environment"
              onChange={handleFileChosen}
            >
              {(props) => (
                <Button
                  {...props}
                  size="compact-xs"
                  color="blue"
                  variant="light"
                  radius="md"
                  leftSection={<IconCamera size={13} />}
                  loading={isUploadingReceipt}
                >
                  Camera
                </Button>
              )}
            </FileButton>
            <FileButton
              accept="image/*,.json,.pdf,.csv,application/json,application/pdf,text/csv"
              onChange={handleFileChosen}
            >
              {(props) => (
                <Button
                  {...props}
                  size="compact-xs"
                  color="indigo"
                  variant="light"
                  radius="md"
                  leftSection={<IconUpload size={13} />}
                  loading={isUploadingReceipt}
                >
                  Upload
                </Button>
              )}
            </FileButton>
          </Group>
        </Group>

        {/* Mobile / Responsive Quick Action Grid */}
        <SimpleGrid cols={{ base: 2, xs: 3, sm: 5 }} spacing={6}>
          {presets.map((tpl) => (
            <Button
              key={tpl.id}
              size="xs"
              variant="default"
              radius="md"
              onClick={() => handleOpenTemplate(tpl)}
              leftSection={<Text size="sm">{tpl.icon}</Text>}
              style={{
                boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
                justifyContent: 'flex-start',
                paddingLeft: 8,
                paddingRight: 8,
                height: 36,
              }}
            >
              <Text size="xs" fw={600} truncate>
                {tpl.id === 'tpl_diaper'
                  ? 'Marcus Pooped'
                  : tpl.id === 'tpl_dining'
                  ? 'Dining'
                  : tpl.id === 'tpl_grocery'
                  ? 'Shopping'
                  : tpl.id === 'tpl_dog'
                  ? 'Dog walk'
                  : tpl.id === 'tpl_swimming' || tpl.id === 'tpl_pool'
                  ? 'Swimming'
                  : tpl.name}
              </Text>
            </Button>
          ))}
        </SimpleGrid>
      </Card>

      {/* Drawer: Full Template Grid */}
      <Drawer
        opened={drawerOpened}
        onClose={() => setDrawerOpened(false)}
        title={<Text fw={700}>Quick Action Templates ({templates.length})</Text>}
        position="bottom"
        size="lg"
        radius="lg"
      >
        <Text size="xs" c="dimmed" mb="md">
          Pre-fills time, duration, person, and notes with 1-tap confirmation.
        </Text>
        <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm">
          {templates.map((tpl) => (
            <Card
              key={tpl.id}
              withBorder
              radius="md"
              p="sm"
              style={{ cursor: 'pointer' }}
              onClick={() => handleOpenTemplate(tpl)}
            >
              <Group gap="xs" mb="xs">
                <Text size="xl">{tpl.icon}</Text>
                <Box style={{ overflow: 'hidden' }}>
                  <Text size="xs" fw={700} truncate>
                    {tpl.name}
                  </Text>
                  <Text size="10px" c="dimmed">
                    {tpl.default_person} • {tpl.default_duration_minutes}m
                  </Text>
                </Box>
              </Group>
              <Text size="11px" c="dark.3" lineClamp={2}>
                {tpl.default_description}
              </Text>
            </Card>
          ))}
        </SimpleGrid>
      </Drawer>

      {/* 1. Modal: Editable Quick Event (Diaper, Routine Presets) */}
      <Modal
        opened={quickModalOpened}
        onClose={() => setQuickModalOpened(false)}
        title={
          <Group gap="xs">
            <Text size="xl">{selectedTemplate?.icon}</Text>
            <Text fw={700}>{selectedTemplate?.name}</Text>
          </Group>
        }
        radius="md"
        centered
      >
        <Stack gap="sm">
          <TextInput
            label="Event Title"
            value={title}
            onChange={(e) => setTitle(e.currentTarget.value)}
          />

          {/* START TIME & QUICK DURATION ADJUST */}
          <TextInput
            label="Start Time"
            type="datetime-local"
            value={startTime}
            onChange={(e) => setStartTime(e.currentTarget.value)}
            leftSection={<IconClock size={16} />}
          />

          <Box>
            <Group justify="space-between" mb={6}>
              <Text size="xs" fw={500}>
                Duration
              </Text>
              <Badge size="sm" variant="light" color="blue">
                {durationMinutes} min • Ends at {computeEndTimeDisplay(startTime, durationMinutes)}
              </Badge>
            </Group>
            <Group gap="xs">
              {[15, 30, 45, 60, 90, 120].map((mins) => (
                <Button
                  key={mins}
                  size="xs"
                  variant={durationMinutes === mins ? 'filled' : 'default'}
                  color={durationMinutes === mins ? 'blue' : undefined}
                  onClick={() => setDurationMinutes(mins)}
                >
                  {mins < 60 ? `${mins}m` : mins === 60 ? '1 hr' : `${mins / 60} hrs`}
                </Button>
              ))}
            </Group>
          </Box>

          <Select
            label="Person Involved"
            data={['Marcus', 'Dad', 'Mom', 'Family']}
            value={person}
            onChange={(val) => setPerson(val || 'Marcus')}
            leftSection={<IconUser size={16} />}
          />

          {selectedTemplate?.id === 'tpl_diaper' && (
            <Box>
              <Text size="xs" fw={500} mb={4}>
                Diaper Status
              </Text>
              <Group gap="xs">
                <Chip.Group value={diaperTag} onChange={(val) => setDiaperTag(val as string)}>
                  <Chip value="Poop" color="orange">💩 Poop</Chip>
                  <Chip value="Wet" color="cyan">💧 Wet</Chip>
                  <Chip value="Both" color="red">💩+💧 Both</Chip>
                  <Chip value="Cream" color="teal">🧴 Diaper Cream</Chip>
                </Chip.Group>
              </Group>
            </Box>
          )}

          <TextInput
            label="Location"
            value={location}
            onChange={(e) => setLocation(e.currentTarget.value)}
            leftSection={<IconMapPin size={16} />}
          />

          <Textarea
            label="Notes / Description"
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            rows={2}
          />

          <Group justify="flex-end" mt="md" gap="xs">
            <Button size="xs" variant="default" onClick={() => setQuickModalOpened(false)}>
              Cancel
            </Button>
            <Button size="xs" color="blue" onClick={handleSaveQuickEvent} leftSection={<IconCheck size={14} />}>
              Save
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* 2. UNIFIED SMART INTAKE MODAL (All Receipt & Document Cases) */}
      <Modal
        opened={smartIntakeOpened}
        onClose={() => setSmartIntakeOpened(false)}
        closeOnClickOutside={false}
        closeOnEscape={false}
        title={
          <Group gap="xs">
            <Text size="xl">📸</Text>
            <Text fw={700}>Snap & Log Life Event</Text>
          </Group>
        }
        radius="md"
        size="lg"
        centered
      >
        <Stack gap="sm">
          {/* Intent Category Switcher */}
          <Box>
            <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb={4}>
              Select Event Category
            </Text>
            <SegmentedControl
              fullWidth
              size="xs"
              value={snapIntent}
              onChange={(val) => openSmartIntake(val as SnapIntent)}
              data={[
                { label: '🍽️ Dining', value: 'DINING' },
                { label: '🛒 Store', value: 'SHOPPING' },
                { label: '🚗 Auto/Home', value: 'MAINTENANCE' },
                { label: '🩺 Medical', value: 'MEDICAL' },
                { label: '⚡ Other', value: 'CUSTOM' },
              ]}
            />
          </Box>

          {/* Hidden native camera/file input */}
          <input
            type="file"
            ref={fileInputRef}
            accept="image/*"
            capture="environment"
            style={{ display: 'none' }}
            onChange={handlePhotoCaptured}
          />

          {/* Photo Capture Preparation (Zero Scan/LLM yet!) */}
          <Paper p="sm" radius="md" withBorder bg={receiptImageName ? 'teal.0' : 'gray.0'}>
            <Group justify="space-between" align="center">
              <Group gap="xs">
                <ThemeIcon color={receiptImageName ? 'teal' : 'blue'} size="lg" radius="xl">
                  <IconCamera size={20} />
                </ThemeIcon>
                <Box>
                  <Text size="xs" fw={700} c={receiptImageName ? 'teal.9' : 'dark.4'}>
                    {receiptImageName ? `Attached: ${receiptImageName}` : 'Prepare to upload receipt or document photo'}
                  </Text>
                  <Text size="11px" c="dimmed">
                    {receiptImageName
                      ? 'Photo ready for background upload & AI extraction'
                      : 'Snap receipt now or upload a picture from your camera roll'}
                  </Text>
                </Box>
              </Group>

              <Group gap="xs">
                <Button
                  size="xs"
                  color={receiptImageName ? 'gray' : 'blue'}
                  variant={receiptImageName ? 'outline' : 'filled'}
                  leftSection={<IconCamera size={14} />}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {receiptImageName ? 'Retake' : 'Take Photo'}
                </Button>
                {!receiptImageName && (
                  <Button
                    size="xs"
                    color="teal"
                    variant="light"
                    onClick={simulateCameraSnap}
                  >
                    Simulate Snap
                  </Button>
                )}
              </Group>
            </Group>
          </Paper>

          {/* Event Title */}
          <TextInput
            label="Event Title"
            value={snapTitle}
            onChange={(e) => setSnapTitle(e.currentTarget.value)}
            required
          />

          {/* People Involved (Who was there?) */}
          <Box>
            <Text size="xs" fw={500} mb={4}>
              People Involved (Who was present?)
            </Text>
            <Chip.Group multiple value={snapPeople} onChange={setSnapPeople}>
              <Group gap="xs">
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
                <Chip value="Guest" size="xs">Guest / Friend</Chip>
              </Group>
            </Chip.Group>
          </Box>

          {/* START TIME & QUICK DURATION ADJUST */}
          <TextInput
            label="Start Time"
            type="datetime-local"
            value={snapStartTime}
            onChange={(e) => setSnapStartTime(e.currentTarget.value)}
            leftSection={<IconClock size={16} />}
          />

          <Box>
            <Group justify="space-between" mb={6}>
              <Text size="xs" fw={500}>
                Duration (Concluded Recently)
              </Text>
              <Badge size="sm" variant="light" color="teal">
                {snapDurationMinutes} min • Concluded at {computeEndTimeDisplay(snapStartTime, snapDurationMinutes)}
              </Badge>
            </Group>
            <Group gap="xs">
              {[15, 30, 45, 60, 90, 120].map((mins) => (
                <Button
                  key={mins}
                  size="xs"
                  variant={snapDurationMinutes === mins ? 'filled' : 'default'}
                  color={snapDurationMinutes === mins ? 'teal' : undefined}
                  onClick={() => handleIntakeDurationChange(mins)}
                >
                  {mins < 60 ? `${mins}m` : mins === 60 ? '1 hr' : `${mins / 60} hrs`}
                </Button>
              ))}
            </Group>
          </Box>

          {/* Prepopulated Location with Deferred AI Refinement Note */}
          <Box>
            <TextInput
              label="Location"
              value={snapLocation}
              onChange={(e) => setSnapLocation(e.currentTarget.value)}
              leftSection={<IconMapPin size={16} />}
            />
            <Text size="10px" c="blue.7" mt={2} fw={500}>
              ✨ If the AI later extracts a more specific address from the receipt/invoice header, it will automatically update this field.
            </Text>
          </Box>

          {/* ── INTENT SPECIFIC HUMAN CONTEXT FIELDS ── */}

          {/* Case 1: Dining */}
          {snapIntent === 'DINING' && (
            <Paper p="xs" withBorder radius="md" bg="gray.0">
              <Group justify="space-between" align="center">
                <Text size="xs" fw={500}>
                  Experience Rating:
                </Text>
                <Rating value={diningRating} onChange={setDiningRating} size="md" />
              </Group>
            </Paper>
          )}

          {/* Case 2: Store / Grocery */}
          {snapIntent === 'SHOPPING' && (
            <Paper p="xs" withBorder radius="md" bg="gray.0">
              <Checkbox
                checked={storePantryRestock}
                onChange={(e) => setStorePantryRestock(e.currentTarget.checked)}
                label="Automatically update Pantry stock & cross off items from 7-day shopping list"
              />
            </Paper>
          )}

          {/* Case 3: Vehicle & Home Maintenance */}
          {snapIntent === 'MAINTENANCE' && (
            <Paper p="xs" withBorder radius="md" bg="gray.0">
              <TextInput
                label="Service Type"
                value={maintService}
                onChange={(e) => setMaintService(e.currentTarget.value)}
              />
            </Paper>
          )}

          {/* Case 4: Medical / Dental / Rx */}
          {snapIntent === 'MEDICAL' && (
            <Paper p="xs" withBorder radius="md" bg="gray.0">
              <Group grow mb="xs">
                <Select
                  label="Medical Provider Type"
                  data={['Pediatrician', 'Dentist', 'Eye Doctor', 'Urgent Care', 'Pharmacy']}
                  value={medSpecialty}
                  onChange={(v) => setMedSpecialty(v || 'Pediatrician')}
                />
                <TextInput
                  label="Diagnosis / Prescription"
                  value={medPrescription}
                  onChange={(e) => setMedPrescription(e.currentTarget.value)}
                />
              </Group>
              <Text size="10px" c="dimmed">
                AI will extract copay receipt amount and next 6-month checkup recall date.
              </Text>
            </Paper>
          )}

          {/* Notes */}
          <Textarea
            label="Notes / Comments"
            value={snapNotes}
            onChange={(e) => setSnapNotes(e.currentTarget.value)}
            placeholder="Additional notes for your family ledger..."
            rows={2}
          />

          <Group mt="md">
            <Button
              color="blue"
              size="sm"
              fullWidth
              onClick={handleSaveSmartIntake}
              leftSection={<IconCheck size={16} />}
            >
              Save Event
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* 3. SIMPLE / COMPACT QUICK ADD MODAL (1-Click Log with prepopulated time) */}
      <SimpleQuickAddModal
        opened={simpleModalOpened}
        onClose={() => setSimpleModalOpened(false)}
        template={simpleTemplate}
        onConfirm={onSaveQuickEvent}
      />
    </>
  );
};
