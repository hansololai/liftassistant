import React, { useState } from 'react';
import {
  Card,
  Text,
  Badge,
  Group,
  Stack,
  Button,
  Tabs,
  Checkbox,
  Progress,
  Paper,
  Box,
  SimpleGrid,
  Modal,
  Table,
  ActionIcon,
  ThemeIcon,
  Tooltip,
  NumberInput,
  Select,
} from '@mantine/core';
import {
  IconShoppingCart,
  IconBuildingStore,
  IconAlertCircle,
  IconCheck,
  IconCalendarEvent,
  IconDeviceTablet,
  IconScale,
  IconMinus,
  IconPlus,
  IconPackage,
  IconSparkles,
} from '@tabler/icons-react';
import { ProductItem, ShoppingListItem, ProductUnitConversion, StoreItemMultiplier } from '../types';
import { CreateProductModal } from './CreateProductModal';

interface Props {
  products: ProductItem[];
  shoppingList: ShoppingListItem[];
  conversions?: ProductUnitConversion[];
  multipliers?: StoreItemMultiplier[];
  onToggleShoppingItem: (id: string) => void;
  onConsumeProduct: (productId: string, amount: number) => void;
  onCreateProduct?: (product: ProductItem, conversion: ProductUnitConversion) => void;
  onUpsertMultiplier?: (store: string, item: string, multiplier: number, productId?: string) => void;
}

export const PantryView: React.FC<Props> = ({
  products,
  shoppingList,
  conversions = [],
  multipliers = [],
  onToggleShoppingItem,
  onConsumeProduct,
  onCreateProduct,
  onUpsertMultiplier,
}) => {
  const [selectedStore, setSelectedStore] = useState<string>('Costco');
  const [conversionsModalOpened, setConversionsModalOpened] = useState(false);
  const [createProductModalOpened, setCreateProductModalOpened] = useState(false);

  const handleMultiplierChange = (store: string, item: string, val: number | string, productId?: string) => {
    const num = typeof val === 'number' ? val : parseFloat(val);
    if (!isNaN(num) && num > 0 && onUpsertMultiplier) {
      onUpsertMultiplier(store, item, num, productId);
    }
  };

  const handleProductChange = (store: string, item: string, multiplier: number, newProductId: string | null) => {
    if (onUpsertMultiplier) {
      onUpsertMultiplier(store, item, multiplier, newProductId || undefined);
    }
  };

  // Stores available in the shopping list
  const stores = Array.from(new Set(shoppingList.map((item) => item.store_name)));

  const storeItems = shoppingList.filter((item) => item.store_name === selectedStore);

  // Products with >= 7 days of supply (hidden from shopping list)
  const sufficientProducts = products.filter((p) => p.days_runway >= 7.0);

  // Products pinned to the Fridge Door Pad
  const fridgePadProducts = products.filter((p) => p.is_fridge_quick_tile);

  const getProductEmoji = (name: string) => {
    const lower = name.toLowerCase();
    if (lower.includes('toilet') || lower.includes('bath tissue')) return '🧻';
    if (lower.includes('milk')) return '🥛';
    if (lower.includes('egg')) return '🥚';
    if (lower.includes('paper towel')) return '🧻';
    if (lower.includes('yogurt')) return '🥣';
    if (lower.includes('pod') || lower.includes('dish')) return '🧼';
    if (lower.includes('banana')) return '🍌';
    if (lower.includes('apple')) return '🍎';
    return '📦';
  };

  return (
    <Stack gap="md">
      {/* 1. Fridge Door Pad: Tap-to-Consume Tactile Tiles */}
      <Card withBorder radius="md" p="md" bg="blue.0" style={{ borderColor: 'var(--mantine-color-blue-2)' }}>
        <Group justify="space-between" align="center" mb="xs">
          <Group gap="xs">
            <ThemeIcon color="blue" size="md" radius="xl">
              <IconDeviceTablet size={18} />
            </ThemeIcon>
            <Box>
              <Text fw={800} size="sm" c="blue.9">
                📱 Fridge Door Pad: Tap-to-Consume
              </Text>
              <Text size="11px" c="dark.3">
                Click when grocery item is taken from fridge or pantry (tablet-friendly 1-tap decrement)
              </Text>
            </Box>
          </Group>
          <Group gap="xs">
            <Button
              size="xs"
              variant="filled"
              color="teal"
              leftSection={<IconPlus size={14} />}
              onClick={() => setCreateProductModalOpened(true)}
            >
              + Add Product to Stock
            </Button>
            <Button
              size="xs"
              variant="light"
              color="blue"
              leftSection={<IconScale size={14} />}
              onClick={() => setConversionsModalOpened(true)}
            >
              Bulk Unit Multiplier Map ({conversions.length})
            </Button>
          </Group>
        </Group>

        <SimpleGrid cols={{ base: 2, sm: 3, md: 4 }} spacing="xs" mt="xs">
          {fridgePadProducts.map((p) => {
            const isLow = p.days_runway < 7;
            const step = p.consume_step || 1;
            const stepLabel = p.consume_step_label || `-${step} ${p.unit}`;

            return (
              <Card
                key={p.id}
                withBorder
                radius="md"
                p="xs"
                bg="white"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
                }}
              >
                <Box>
                  <Group justify="space-between" align="flex-start" gap={2} mb={2}>
                    <Text size="xl">{getProductEmoji(p.name)}</Text>
                    <Badge size="xs" color={isLow ? 'red' : 'teal'} variant="light">
                      {p.days_runway}d left
                    </Badge>
                  </Group>

                  <Text size="xs" fw={700} lineClamp={1}>
                    {p.name}
                  </Text>

                  <Text size="13px" fw={800} c={isLow ? 'red.8' : 'blue.9'}>
                    {p.current_stock} <Text span size="10px" fw={500} c="dimmed">{p.unit}</Text>
                  </Text>

                  {p.purchase_unit && p.unit_multiplier && (
                    <Badge size="9px" color="gray" variant="outline" mt={2} mb={4} p={3}>
                      Costco {p.purchase_unit} = {p.unit_multiplier} {p.unit}
                    </Badge>
                  )}
                </Box>

                {/* Tactile Consume Button */}
                <Group gap={4} mt="xs" grow>
                  <Button
                    size="xs"
                    color="red"
                    variant="filled"
                    leftSection={<IconMinus size={12} />}
                    onClick={() => onConsumeProduct(p.id, step)}
                    style={{ flex: 1 }}
                  >
                    {stepLabel}
                  </Button>
                  <ActionIcon
                    size="input-xs"
                    variant="default"
                    color="gray"
                    onClick={() => onConsumeProduct(p.id, -step)}
                    title="Restock / Undo"
                  >
                    <IconPlus size={12} />
                  </ActionIcon>
                </Group>
              </Card>
            );
          })}
        </SimpleGrid>
      </Card>

      {/* 2. Header & 7-Day Horizon Banner */}
      <Card withBorder radius="md" p="md" bg="teal.0" style={{ borderColor: 'var(--mantine-color-teal-2)' }}>
        <Group justify="space-between" align="flex-start">
          <Box>
            <Text fw={800} size="md" c="teal.9">
              7-Day Smart Shopping List
            </Text>
            <Text size="xs" c="dark.3">
              Only items with &lt; 7 days supply are queued. Items sufficient for the week are automatically hidden.
            </Text>
          </Box>
          <Badge color="teal" variant="light">Weekly Cadence</Badge>
        </Group>

        <Group gap="xs" mt="sm">
          <Text size="11px" c="teal.8" fw={600}>
            ✓ Sufficient this week (Hidden):
          </Text>
          {sufficientProducts.map((p) => (
            <Badge key={p.id} size="xs" color="gray" variant="outline">
              {p.name} ({p.days_runway}d left)
            </Badge>
          ))}
        </Group>
      </Card>

      {/* 3. Store-Specific Tabs */}
      <Card withBorder radius="md" p="md">
        <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb="xs">
          Select Shopping Destination
        </Text>
        <Group gap="xs" mb="md">
          {stores.map((store) => {
            const count = shoppingList.filter((s) => s.store_name === store && !s.checked).length;
            const isSelected = selectedStore === store;
            return (
              <Button
                key={store}
                size="xs"
                variant={isSelected ? 'filled' : 'light'}
                color="blue"
                radius="xl"
                onClick={() => setSelectedStore(store)}
                rightSection={count > 0 ? <Badge size="xs" color="red" circle>{count}</Badge> : undefined}
              >
                {store}
              </Button>
            );
          })}
        </Group>

        {/* Items for Selected Store */}
        <Stack gap="xs">
          {storeItems.map((item) => (
            <Paper key={item.id} p="sm" withBorder radius="sm" bg={item.checked ? 'gray.1' : 'white'}>
              <Group justify="space-between">
                <Checkbox
                  checked={item.checked}
                  onChange={() => onToggleShoppingItem(item.id)}
                  label={
                    <Box>
                      <Text
                        size="sm"
                        fw={600}
                        style={{ textDecoration: item.checked ? 'line-through' : 'none' }}
                      >
                        {item.item_name}
                      </Text>
                      <Text size="xs" c={item.days_runway < 3 ? 'red' : 'dimmed'}>
                        {item.amount} {item.unit} • Runs out in {item.days_runway} days
                      </Text>
                    </Box>
                  }
                />
                <Badge size="xs" color={item.days_runway < 3 ? 'red' : 'yellow'} variant="light">
                  {item.days_runway < 3 ? 'Urgent' : 'This Week'}
                </Badge>
              </Group>
            </Paper>
          ))}
        </Stack>
      </Card>

      {/* 4. Full Pantry Stock Ledger */}
      <Card withBorder radius="md" p="md">
        <Group justify="space-between" mb="xs">
          <Text fw={700} size="sm">
            Pantry Stock & Burn-Rate Tracker ({products.length} Products)
          </Text>
          <Badge size="xs" color="gray">Grocy Ledger Sync</Badge>
        </Group>

        <Stack gap="sm">
          {products.map((p) => {
            const isLow = p.days_runway < 7;
            const step = p.consume_step || 1;
            return (
              <Paper key={p.id} p="xs" withBorder radius="sm">
                <Group justify="space-between" mb={4}>
                  <Box>
                    <Group gap="xs">
                      <Text size="lg">{getProductEmoji(p.name)}</Text>
                      <Box>
                        <Text size="sm" fw={600}>
                          {p.name}
                        </Text>
                        <Text size="11px" c="dimmed">
                          Location: {p.location} • Preferred: {p.store_name}
                          {p.purchase_unit && p.unit_multiplier && ` • (1 ${p.purchase_unit} = ${p.unit_multiplier} ${p.unit})`}
                        </Text>
                      </Box>
                    </Group>
                  </Box>
                  <Group gap="xs" align="center">
                    <Box style={{ textAlign: 'right' }}>
                      <Text size="sm" fw={700}>
                        {p.current_stock} {p.unit}
                      </Text>
                      <Text size="11px" c={isLow ? 'red' : 'teal'} fw={500}>
                        {p.days_runway} days runway
                      </Text>
                    </Box>
                    <ActionIcon
                      size="sm"
                      variant="light"
                      color="red"
                      onClick={() => onConsumeProduct(p.id, step)}
                      title={`Consume ${step} ${p.unit}`}
                    >
                      <IconMinus size={14} />
                    </ActionIcon>
                    <ActionIcon
                      size="sm"
                      variant="light"
                      color="teal"
                      onClick={() => onConsumeProduct(p.id, -step)}
                      title={`Restock ${step} ${p.unit}`}
                    >
                      <IconPlus size={14} />
                    </ActionIcon>
                  </Group>
                </Group>
                <Progress
                  value={Math.min(100, (p.days_runway / 14) * 100)}
                  color={isLow ? 'orange' : 'teal'}
                  size="xs"
                />
              </Paper>
            );
          })}
        </Stack>
      </Card>

      {/* Modal: Bulk Purchase Unit Multiplier Map */}
      <Modal
        opened={conversionsModalOpened}
        onClose={() => setConversionsModalOpened(false)}
        title={
          <Group gap="xs">
            <ThemeIcon color="blue" size="md" radius="xl">
              <IconPackage size={16} />
            </ThemeIcon>
            <Text fw={700}>Unit Multipliers (Store, Item, Multiplier)</Text>
          </Group>
        }
        size="lg"
        radius="md"
        centered
      >
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            Multipliers & Product Linking table: when items from bulk stores (Costco, Sam's Club) are ingested, receipt items are mapped directly to canonical stock products and multiplied by this ratio.
          </Text>

          <Table striped withTableBorder withColumnBorders>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Store</Table.Th>
                <Table.Th>Receipt Item</Table.Th>
                <Table.Th>Linked Stock Product</Table.Th>
                <Table.Th style={{ width: 120, textAlign: 'right' }}>Multiplier</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {multipliers.map((m, idx) => (
                <Table.Tr key={`${m.store}-${m.item}-${idx}`}>
                  <Table.Td>
                    <Badge size="xs" color="blue" variant="light">{m.store}</Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" fw={600}>{m.item}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Select
                      size="xs"
                      w={210}
                      clearable
                      searchable
                      value={m.product_id || null}
                      placeholder="Select stock product..."
                      data={products.map((p) => ({ value: p.id, label: p.name }))}
                      onChange={(newProdId) => handleProductChange(m.store, m.item, m.multiplier, newProdId)}
                    />
                  </Table.Td>
                  <Table.Td style={{ textAlign: 'right' }}>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <Text size="xs" c="dimmed">×</Text>
                      <NumberInput
                        size="xs"
                        w={75}
                        min={0.1}
                        step={1}
                        value={m.multiplier}
                        onChange={(val) => handleMultiplierChange(m.store, m.item, val, m.product_id)}
                      />
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>

          <Paper p="xs" withBorder radius="sm" bg="gray.0">
            <Group gap="xs">
              <IconSparkles size={16} color="var(--mantine-color-blue-6)" />
              <Text size="11px" c="dark.3">
                <strong>Example:</strong> Buying 1 pack of Costco Toilet Paper automatically registers <strong>+36 rolls</strong> on your ledger. Clicking the fridge pad decrements <strong>-1 roll</strong> each time!
              </Text>
            </Group>
          </Paper>
        </Stack>
      </Modal>

      {/* 5. Create Product & Bulk Multiplier Mapping Modal */}
      <CreateProductModal
        opened={createProductModalOpened}
        onClose={() => setCreateProductModalOpened(false)}
        onSave={(newProd, newConv) => {
          if (onCreateProduct) {
            onCreateProduct(newProd, newConv);
          }
          setCreateProductModalOpened(false);
        }}
      />
    </Stack>
  );
};
