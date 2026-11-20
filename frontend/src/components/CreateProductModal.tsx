import React, { useState, useEffect } from 'react';
import {
  Modal,
  TextInput,
  Select,
  NumberInput,
  Checkbox,
  Group,
  Stack,
  Button,
  Paper,
  Text,
  Badge,
  Alert,
  ThemeIcon,
  Divider,
  Box,
  SimpleGrid,
} from '@mantine/core';
import {
  IconPackage,
  IconScale,
  IconCheck,
  IconSparkles,
  IconArrowRight,
  IconInfoCircle,
} from '@tabler/icons-react';
import { ProductItem, ProductUnitConversion } from '../types';

interface Props {
  opened: boolean;
  onClose: () => void;
  onSave: (product: ProductItem, conversion: ProductUnitConversion) => void;
  initialData?: {
    name?: string;
    store_name?: string;
    purchase_unit?: string;
    unit_price?: number;
    receipt_quantity?: number;
  };
}

const CATEGORY_OPTIONS = [
  { value: 'household', label: '🧻 Household & Paper Goods' },
  { value: 'dairy', label: '🥛 Dairy & Eggs' },
  { value: 'produce', label: '🥬 Produce & Fruits' },
  { value: 'meat', label: '🥩 Meat & Seafood' },
  { value: 'pantry', label: '🥫 Pantry & Dry Goods' },
  { value: 'bakery', label: '🍞 Bakery & Bread' },
  { value: 'snacks', label: '🍪 Snacks & Sweets' },
  { value: 'beverages', label: '🧃 Beverages' },
  { value: 'frozen', label: '🧊 Frozen Foods' },
  { value: 'personal_care', label: '🧴 Personal Care & Pharmacy' },
];

const COMMON_PURCHASE_UNITS = [
  { value: 'pack', label: 'pack (Multi-pack / Package)' },
  { value: 'box', label: 'box' },
  { value: 'case', label: 'case' },
  { value: 'tub', label: 'tub' },
  { value: 'bag', label: 'bag' },
  { value: 'bunch', label: 'bunch' },
  { value: 'lb', label: 'lb (Pounds)' },
  { value: 'ea', label: 'ea (Single Unit)' },
];

const COMMON_STOCK_UNITS = [
  { value: 'roll', label: 'rolls (e.g. paper towels, toilet paper)' },
  { value: 'ea', label: 'items / units' },
  { value: 'can', label: 'cans' },
  { value: 'bottle', label: 'bottles' },
  { value: 'lb', label: 'lbs (Pounds)' },
  { value: 'oz', label: 'oz (Ounces)' },
  { value: 'gal', label: 'gallons' },
  { value: 'egg', label: 'eggs' },
  { value: 'pod', label: 'pods (Dishwasher / Laundry)' },
  { value: 'cup', label: 'cups' },
];

export const CreateProductModal: React.FC<Props> = ({
  opened,
  onClose,
  onSave,
  initialData,
}) => {
  const [name, setName] = useState('');
  const [category, setCategory] = useState<string>('pantry');
  const [storeName, setStoreName] = useState('Costco Wholesale');
  const [purchaseUnit, setPurchaseUnit] = useState('pack');
  const [stockUnit, setStockUnit] = useState('ea');
  const [unitMultiplier, setUnitMultiplier] = useState<number>(1);
  const [dailyBurnRate, setDailyBurnRate] = useState<number>(0.2);
  const [initialStock, setInitialStock] = useState<number>(0);
  const [isFridgeQuickTile, setIsFridgeQuickTile] = useState(false);

  useEffect(() => {
    if (opened && initialData) {
      const cleanName = initialData.name
        ? initialData.name
            .replace(/^KS\s+/i, 'Kirkland ')
            .replace(/\s+\d+\/\w+$/i, '')
            .trim()
        : '';
      setName(cleanName || initialData.name || '');
      setStoreName(initialData.store_name || 'Costco Wholesale');

      // Auto-detect unit and multiplier heuristics
      const raw = (initialData.name || '').toLowerCase();
      if (raw.includes('paper towel')) {
        setCategory('household');
        setPurchaseUnit('pack');
        setStockUnit('roll');
        setUnitMultiplier(12);
        setIsFridgeQuickTile(true);
      } else if (raw.includes('bath tissue') || raw.includes('toilet')) {
        setCategory('household');
        setPurchaseUnit('pack');
        setStockUnit('roll');
        setUnitMultiplier(36);
        setIsFridgeQuickTile(true);
      } else if (raw.includes('milk')) {
        setCategory('dairy');
        setPurchaseUnit('pack');
        setStockUnit('gal');
        setUnitMultiplier(2);
        setIsFridgeQuickTile(true);
      } else if (raw.includes('egg')) {
        setCategory('dairy');
        setPurchaseUnit('case');
        setStockUnit('egg');
        setUnitMultiplier(48);
        setIsFridgeQuickTile(true);
      } else if (raw.includes('pod') || raw.includes('dish')) {
        setCategory('household');
        setPurchaseUnit('tub');
        setStockUnit('pod');
        setUnitMultiplier(90);
        setIsFridgeQuickTile(true);
      } else if (raw.includes('pork') || raw.includes('chicken') || raw.includes('beef')) {
        setCategory('meat');
        setPurchaseUnit('lb');
        setStockUnit('lb');
        setUnitMultiplier(1);
        setIsFridgeQuickTile(false);
      } else if (raw.includes('berry') || raw.includes('banana') || raw.includes('apple')) {
        setCategory('produce');
        setPurchaseUnit(initialData.purchase_unit || 'pack');
        setStockUnit('ea');
        setUnitMultiplier(1);
        setIsFridgeQuickTile(true);
      } else {
        setCategory('pantry');
        setPurchaseUnit(initialData.purchase_unit || 'pack');
        setStockUnit('ea');
        setUnitMultiplier(1);
      }
    }
  }, [opened, initialData]);

  const receiptQty = initialData?.receipt_quantity ?? 1;
  const previewStockAdded = parseFloat((receiptQty * (unitMultiplier || 1)).toFixed(2));
  const estimatedRunwayDays =
    dailyBurnRate > 0 && previewStockAdded > 0
      ? Math.round(previewStockAdded / dailyBurnRate)
      : null;

  const handleSave = () => {
    if (!name.trim()) return;

    const productId = `prod_${Date.now()}`;
    const newProduct: ProductItem = {
      id: productId,
      name: name.trim(),
      category,
      current_stock: initialStock,
      unit: stockUnit,
      purchase_unit: purchaseUnit,
      unit_multiplier: unitMultiplier,
      consume_step: 1,
      consume_step_label: `-1 ${stockUnit}`,
      daily_burn_rate: dailyBurnRate,
      days_runway: dailyBurnRate > 0 ? parseFloat((initialStock / dailyBurnRate).toFixed(1)) : 999,
      store_name: storeName,
      location: category === 'dairy' || category === 'meat' ? 'Kitchen Fridge' : 'Main Pantry',
      is_fridge_quick_tile: isFridgeQuickTile,
    };

    const newConversion: ProductUnitConversion = {
      id: `conv_${Date.now()}`,
      product_id: productId,
      product_name: name.trim(),
      store_name: storeName,
      receipt_raw_text: initialData?.name || name.trim(),
      purchase_unit: purchaseUnit,
      stock_unit: stockUnit,
      unit_multiplier: unitMultiplier,
    };

    onSave(newProduct, newConversion);
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <Group gap="xs">
          <ThemeIcon color="teal" size="md" radius="xl">
            <IconPackage size={18} />
          </ThemeIcon>
          <Box>
            <Text fw={700} size="md">
              Create Product & Stock Multiplier Mapping
            </Text>
            <Text size="11px" c="dimmed">
              Define catalog item and configure how purchases increase your stock
            </Text>
          </Box>
        </Group>
      }
      size="md"
      radius="md"
    >
      <Stack gap="md">
        {initialData?.name && (
          <Alert color="blue" variant="light" p="xs">
            <Group gap="xs">
              <IconInfoCircle size={16} />
              <Text size="xs">
                Unlinked receipt item: <strong>"{initialData.name}"</strong>
              </Text>
            </Group>
          </Alert>
        )}

        {/* 1. Basic Identity */}
        <TextInput
          label="Product Name"
          placeholder="e.g. Kirkland Signature Paper Towels"
          required
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />

        <SimpleGrid cols={2} spacing="xs">
          <Select
            label="Category"
            data={CATEGORY_OPTIONS}
            value={category}
            onChange={(val) => setCategory(val || 'pantry')}
            required
          />
          <TextInput
            label="Preferred Store"
            placeholder="Costco Wholesale"
            value={storeName}
            onChange={(e) => setStoreName(e.currentTarget.value)}
          />
        </SimpleGrid>

        <Divider label="Stock Unit Conversion Mapping" labelPosition="center" />

        {/* 2. Packaging Multiplier Mapping Box */}
        <Paper p="sm" withBorder radius="md" bg="teal.0" style={{ borderColor: 'var(--mantine-color-teal-3)' }}>
          <Group justify="space-between" mb="xs">
            <Text fw={700} size="xs" c="teal.9">
              📦 BULK UNIT CONVERSION MAPPING
            </Text>
            <Badge size="xs" color="teal">
              Grocy Multiplier
            </Badge>
          </Group>

          <Text size="xs" c="dark.3" mb="sm">
            Specify how many individual stock/consumption items are inside 1 store package.
          </Text>

          <SimpleGrid cols={3} spacing="xs">
            <Select
              label="1 Store Purchase Unit"
              data={COMMON_PURCHASE_UNITS}
              value={purchaseUnit}
              onChange={(val) => setPurchaseUnit(val || 'pack')}
              size="xs"
            />
            <NumberInput
              label="Equals (=) Stock Qty"
              description="Multiplier factor"
              value={unitMultiplier}
              onChange={(val) => setUnitMultiplier(Number(val) || 1)}
              min={0.1}
              step={1}
              size="xs"
            />
            <Select
              label="Pantry Tracking Unit"
              data={COMMON_STOCK_UNITS}
              value={stockUnit}
              onChange={(val) => setStockUnit(val || 'ea')}
              size="xs"
            />
          </SimpleGrid>

          {/* Live Preview Card */}
          <Paper p="xs" mt="sm" withBorder radius="sm" bg="white">
            <Group gap="xs" wrap="nowrap">
              <ThemeIcon color="teal" size="sm" radius="xl">
                <IconSparkles size={14} />
              </ThemeIcon>
              <Text size="xs">
                {initialData?.receipt_quantity ? (
                  <>
                    Buying <strong>{receiptQty} {purchaseUnit}</strong> on this receipt will automatically increase stock by{' '}
                    <strong style={{ color: 'var(--mantine-color-teal-8)' }}>
                      +{previewStockAdded} {stockUnit}
                    </strong>{' '}
                    ({receiptQty} × {unitMultiplier})!
                  </>
                ) : (
                  <>
                    Each <strong>1 {purchaseUnit}</strong> purchased will automatically increase pantry stock by{' '}
                    <strong style={{ color: 'var(--mantine-color-teal-8)' }}>
                      +{unitMultiplier} {stockUnit}
                    </strong>
                    .
                  </>
                )}
              </Text>
            </Group>
          </Paper>
        </Paper>

        {/* 3. Burn Rate & Runway */}
        <SimpleGrid cols={2} spacing="xs">
          <NumberInput
            label={`Daily Burn Rate (${stockUnit}/day)`}
            description="Used to forecast days of runway"
            value={dailyBurnRate}
            onChange={(val) => setDailyBurnRate(Number(val) || 0)}
            min={0}
            step={0.1}
            decimalScale={2}
            size="xs"
          />
          <NumberInput
            label={`Current In-Stock (${stockUnit})`}
            description="Initial count in pantry right now"
            value={initialStock}
            onChange={(val) => setInitialStock(Number(val) || 0)}
            min={0}
            step={1}
            size="xs"
          />
        </SimpleGrid>

        {estimatedRunwayDays !== null && (
          <Text size="11px" c="dimmed">
            📈 At a burn rate of {dailyBurnRate} {stockUnit}/day, a purchase of {previewStockAdded} {stockUnit} will provide approximately{' '}
            <strong>{estimatedRunwayDays} days of supply</strong>.
          </Text>
        )}

        <Checkbox
          label="📱 Pin to Fridge Door Pad"
          description="Add a 1-tap tile to the fridge tablet dashboard for instant consumption"
          checked={isFridgeQuickTile}
          onChange={(e) => setIsFridgeQuickTile(e.currentTarget.checked)}
          color="teal"
          size="xs"
        />

        <Divider />

        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} size="sm">
            Cancel
          </Button>
          <Button
            color="teal"
            size="sm"
            leftSection={<IconCheck size={16} />}
            onClick={handleSave}
            disabled={!name.trim()}
          >
            Create Product & Save Mapping
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};
