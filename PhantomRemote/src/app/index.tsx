import React, { useState, useEffect } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  ScrollView,
  Modal,
  Platform
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Image } from 'expo-image';
import { MaterialCommunityIcons, Ionicons } from '@expo/vector-icons';
import { useFonts } from 'expo-font';
import { OledColors } from '../constants/theme';
import { ExternalLink } from '../components/external-link';

const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

const PHANTOM_GLYPHS = {
  auto: '\ue900',
  monitor: '\ue901',
  slave_master: '\ue902',
  master_slave: '\ue903',
  night: '\ue904',
  manual: '\ue905',
  fan: '\ue906',
  humidity: '\ue907',
  insert: '\ue908',
  home: '\ue909',
  evac: '\ue90a',
  temp_evac: '\ue90b',
} as const;

type PhantomGlyphName = keyof typeof PHANTOM_GLYPHS;

function PhantomGlyph({ name, size = 54, color = '#00ffcc', outline = false }: {
  name: PhantomGlyphName;
  size?: number;
  color?: string;
  outline?: boolean;
}) {
  const glyph = PHANTOM_GLYPHS[name];
  const baseStyle = {
    fontFamily: 'Phantom' as const,
    fontSize: size,
    lineHeight: size,
  };

  return (
    <Text
      style={[
        baseStyle,
        outline
          ? Platform.OS === 'web'
            ? ({
                color: 'transparent',
                WebkitTextStrokeWidth: 1,
                WebkitTextStrokeColor: color,
              } as any)
            : {
                color: 'transparent',
                textShadowColor: color,
                textShadowOffset: { width: 0, height: 0 },
                textShadowRadius: 1,
              }
          : { color },
      ]}
    >
      {glyph}
    </Text>
  );
}

function PhantomLevelGlyphs({ name, level, color }: {
  name: 'fan' | 'humidity';
  level: number;
  color: string;
}) {
  const boundedLevel = Math.max(1, Math.min(3, level));
  return (
    <View style={styles.phantomLevelIcons}>
      {Array.from({ length: 3 }, (_, index) => (
        <PhantomGlyph
          key={`${name}-${index}`}
          name={name}
          size={14 + index * 4}
          color={color}
          outline={index >= boundedLevel}
        />
      ))}
    </View>
  );
}

export interface PhantomState {
  mode: 'AUTO' | 'SLEEP' | 'MANUAL' | 'NONE';
  speed: number;
  humidity: number;
  flux: 'SOUTH_NORTH' | 'EXTRACT' | 'INTAKE' | 'NORTH_SOUTH' | 'NONE';
  night: boolean;
  boost: boolean;
  automation_enabled: boolean;
}

export interface SensorMetrics {
  co2_state: string;
  co2_ppm: number;
  temperature_c: number;
  humidity_pct: number;
  pm1_ugm3: number;
  pm25_ugm3: number;
  pm10_ugm3: number;
  voc_mgm3: number;
  ch2o_mgm3: number;
  battery_pct: number;
  online: boolean;
}

export interface EnvironmentalSensor {
  temperature_c: number;
  humidity_pct: number;
  battery?: string | number;
}

export interface CombinedState {
  phantom: PhantomState;
  sensor: SensorMetrics;
  indoor?: EnvironmentalSensor | null;
  outdoor?: EnvironmentalSensor | null;
}

export interface HistorySample {
  fetched_at: string;
  co2_ppm: number | null;
  temperature_c: number | null;
  humidity_pct: number | null;
  pm1_ugm3: number | null;
  pm25_ugm3: number | null;
  pm10_ugm3: number | null;
  voc_mgm3: number | null;
  ch2o_mgm3: number | null;
  indoor_temperature_c: number | null;
  indoor_humidity_pct: number | null;
  outdoor_temperature_c: number | null;
  outdoor_humidity_pct: number | null;
  online: boolean | number;
  zigbee_online: boolean | number;
}

export interface HistoryResponse {
  history: HistorySample[];
}

type AppView = 'home' | 'diagnostics';
type HomeTab = 'sensors' | 'remote';

interface AutomationLogResponse {
  lines: string[];
  available: boolean;
}

interface PhantomStateHistoryEntry {
  id: number;
  created_at: string;
  state: {
    mode?: string;
    speed?: number;
    humidity?: number;
    flux?: string;
    night?: boolean;
    boost?: boolean;
    automation_enabled?: boolean;
  };
}

interface PhantomStateHistoryResponse {
  history: PhantomStateHistoryEntry[];
  total?: number;
  page?: number;
  page_size?: number;
}

type DiagnosticsTab = 'logs' | 'state_history' | 'state_chart';
type StateRuntimeCategory = 'night' | 'speed_1' | 'speed_2' | 'speed_3';

interface PhantomStateRuntimeResponse {
  durations_seconds: Record<StateRuntimeCategory, number>;
  total_seconds: number;
  started_at: string | null;
  as_of: string;
}

const STATE_RUNTIME_CATEGORIES: Array<{ key: StateRuntimeCategory; label: string; color: string }> = [
  { key: 'night', label: 'Night', color: '#8e9aaf' },
  { key: 'speed_1', label: 'Speed 1', color: '#7ef2d0' },
  { key: 'speed_2', label: 'Speed 2', color: '#3498db' },
  { key: 'speed_3', label: 'Speed 3 · Boost', color: '#f1c40f' },
];
const PHANTOM_UNIT_COUNT = 4;
const HOURS_PER_AVERAGE_YEAR = 365.25 * 24;
const STATE_POWER_WATTS: Record<StateRuntimeCategory, number> = {
  night: 3.9,
  speed_1: 4.2,
  speed_2: 5.5,
  speed_3: 6.7,
};

const getAverageHourlyConsumption = (runtime: PhantomStateRuntimeResponse) => {
  const runtimeSeconds = Math.max(0, runtime.total_seconds);
  if (runtimeSeconds <= 0) return null;

  const wattHours = STATE_RUNTIME_CATEGORIES.reduce((total, { key }) => {
    const seconds = Math.max(0, runtime.durations_seconds[key] ?? 0);
    return total + seconds * STATE_POWER_WATTS[key] / 3600;
  }, 0);

  const kwhPerHour = wattHours * PHANTOM_UNIT_COUNT / (runtimeSeconds / 3600) / 1000;
  return {
    kwhPerHour,
    kwhPerYear: kwhPerHour * HOURS_PER_AVERAGE_YEAR,
    runtimeSeconds,
  };
};

type HistoryMetricKey =
  | 'co2_ppm'
  | 'temperature_c'
  | 'humidity_pct'
  | 'pm1_ugm3'
  | 'pm25_ugm3'
  | 'pm10_ugm3'
  | 'voc_mgm3'
  | 'ch2o_mgm3'
  | 'indoor_temperature_c'
  | 'indoor_humidity_pct'
  | 'outdoor_temperature_c'
  | 'outdoor_humidity_pct';

interface HistoryChartConfig {
  key: HistoryMetricKey;
  label: string;
  unit: string;
  color: string;
  precision?: number;
}

const DEFAULT_PHANTOM: PhantomState = {
  mode: 'AUTO',
  speed: 3,
  humidity: 3,
  flux: 'NONE',
  night: false,
  boost: false,
  automation_enabled: true,
};

const DEFAULT_SENSOR: SensorMetrics = {
  co2_state: 'normal',
  co2_ppm: 0,
  temperature_c: 0,
  humidity_pct: 0,
  pm1_ugm3: 0,
  pm25_ugm3: 0,
  pm10_ugm3: 0,
  voc_mgm3: 0,
  ch2o_mgm3: 0,
  battery_pct: 100,
  online: false,
};

const HISTORY_LIMIT = 24 * 60;
const VISIBLE_CHART_SAMPLES = 60;
const PHANTOM_HISTORY_PAGE_SIZE = 10;

const HISTORY_CHARTS: HistoryChartConfig[] = [
  { key: 'co2_ppm', label: 'CO2', unit: 'ppm', color: '#00ffcc' },
  { key: 'temperature_c', label: 'AIR TEMP', unit: '°C', color: '#f39c12', precision: 1 },
  { key: 'humidity_pct', label: 'AIR HUM', unit: '%', color: '#3498db' },
  { key: 'pm1_ugm3', label: 'PM1.0', unit: 'µg/m³', color: '#7bed9f', precision: 1 },
  { key: 'pm25_ugm3', label: 'PM2.5', unit: 'µg/m³', color: '#a8e6cf', precision: 1 },
  { key: 'pm10_ugm3', label: 'PM10', unit: 'µg/m³', color: '#f1c40f', precision: 1 },
  { key: 'voc_mgm3', label: 'TVOC', unit: 'mg/m³', color: '#e67e22', precision: 3 },
  { key: 'ch2o_mgm3', label: 'HCHO', unit: 'mg/m³', color: '#e74c3c', precision: 3 },
  { key: 'indoor_temperature_c', label: 'INDOOR', unit: '°C', color: '#27ae60', precision: 1 },
  { key: 'indoor_humidity_pct', label: 'INDOOR HUM', unit: '%', color: '#3498db' },
  { key: 'outdoor_temperature_c', label: 'OUTDOOR', unit: '°C', color: '#8e9aaf', precision: 1 },
  { key: 'outdoor_humidity_pct', label: 'OUTDOOR HUM', unit: '%', color: '#5dade2' },
];

const formatMetricNumber = (value: number | null | undefined, precision = 0) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return value.toFixed(precision);
};

const formatHistoryTime = (isoValue?: string) => {
  if (!isoValue) return '--:--';
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return '--:--';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const formatAutomationLogLine = (line: string) => {
  const match = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(\s+.*)$/);
  if (!match) return line;

  const utcDate = new Date(`${match[1].replace(' ', 'T')}Z`);
  if (Number.isNaN(utcDate.getTime())) return line;

  const bucharestTimestamp = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Europe/Bucharest',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(utcDate);

  return `${bucharestTimestamp}${match[2]}`;
};

const formatRuntimeDuration = (seconds: number) => {
  const totalMinutes = Math.floor(seconds / 60);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
};

const getCO2Status = (ppm: number) => {
  if (ppm < 800) return { label: 'Air feels fresh', detail: 'Good for everyday living', color: OledColors.mint };
  if (ppm < 1200) return { label: 'Worth ventilating', detail: 'Air quality is getting elevated', color: OledColors.amber };
  return { label: 'Ventilation needed', detail: 'CO2 is above the comfort range', color: OledColors.coral };
};

const getHistoryChartConfig = (metricKey: HistoryMetricKey) => {
  return HISTORY_CHARTS.find((config) => config.key === metricKey) ?? HISTORY_CHARTS[0];
};

const getHealthyColorForHistoryValue = (metricKey: HistoryMetricKey, value: number | null | undefined, fallbackColor: string) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '#1f1f1f';

  switch (metricKey) {
    case 'co2_ppm':
      if (value < 800) return '#00ffcc';
      if (value < 1200) return '#f39c12';
      return '#e74c3c';
    case 'temperature_c':
    case 'indoor_temperature_c':
    case 'outdoor_temperature_c':
      if (value >= 18 && value <= 24) return '#00ffcc';
      if (value >= 15 && value <= 28) return '#f39c12';
      return '#e74c3c';
    case 'humidity_pct':
    case 'indoor_humidity_pct':
    case 'outdoor_humidity_pct':
      if (value >= 30 && value <= 50) return '#00ffcc';
      if (value >= 25 && value <= 60) return '#f39c12';
      return '#e74c3c';
    case 'pm1_ugm3':
    case 'pm25_ugm3':
    case 'pm10_ugm3':
      if (value < 12) return '#00ffcc';
      if (value < 35.4) return '#a8e6cf';
      if (value < 55.4) return '#f39c12';
      return '#e74c3c';
    case 'voc_mgm3':
      if (value < 0.3) return '#00ffcc';
      if (value < 1.0) return '#f39c12';
      return '#e74c3c';
    case 'ch2o_mgm3':
      if (value < 0.05) return '#00ffcc';
      if (value < 0.1) return '#f39c12';
      return '#e74c3c';
    default:
      return fallbackColor;
  }
};

function MiniHistoryChart({ config, samples }: { config: HistoryChartConfig; samples: HistorySample[] }) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const latestWindowStart = Math.max(samples.length - VISIBLE_CHART_SAMPLES, 0);
  const [windowStart, setWindowStart] = useState(latestWindowStart);
  const boundedWindowStart = Math.min(windowStart, latestWindowStart);
  const totalWindows = Math.max(Math.ceil(samples.length / VISIBLE_CHART_SAMPLES), 1);
  const currentWindow = Math.floor(boundedWindowStart / VISIBLE_CHART_SAMPLES);
  const visibleSamples = samples.slice(boundedWindowStart, boundedWindowStart + VISIBLE_CHART_SAMPLES);
  const values = visibleSamples
    .map((sample) => sample[config.key])
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  const latestValue = values.length > 0 ? values[values.length - 1] : null;
  const selectedSample = selectedIndex !== null ? visibleSamples[selectedIndex] : undefined;
  const selectedValue = selectedSample?.[config.key];
  const displayValue = typeof selectedValue === 'number' && Number.isFinite(selectedValue) ? selectedValue : latestValue;
  const minValue = values.length > 0 ? Math.min(...values) : null;
  const maxValue = values.length > 0 ? Math.max(...values) : null;
  const chartMax = maxValue && maxValue > 0 ? maxValue : 1;
  const displayColor = getHealthyColorForHistoryValue(config.key, displayValue, config.color);
  const displayTime = selectedSample?.fetched_at ?? visibleSamples[visibleSamples.length - 1]?.fetched_at;
  const canPageOlder = boundedWindowStart > 0;
  const canPageNewer = boundedWindowStart < latestWindowStart;

  useEffect(() => {
    setSelectedIndex(null);
    setWindowStart(Math.max(samples.length - VISIBLE_CHART_SAMPLES, 0));
  }, [config.key, samples.length]);

  const showOlderWindow = () => {
    setSelectedIndex(null);
    setWindowStart((currentStart) => Math.max(currentStart - VISIBLE_CHART_SAMPLES, 0));
  };

  const showNewerWindow = () => {
    setSelectedIndex(null);
    setWindowStart((currentStart) => Math.min(currentStart + VISIBLE_CHART_SAMPLES, latestWindowStart));
  };

  const showWindow = (windowIndex: number) => {
    setSelectedIndex(null);
    setWindowStart(Math.min(windowIndex * VISIBLE_CHART_SAMPLES, latestWindowStart));
  };

  return (
    <View style={styles.historyChartCard}>
      <View style={styles.historyChartHeader}>
        <View>
          <Text style={styles.historyChartLabel}>SELECTED READING · {config.label}</Text>
          <Text style={[styles.historyChartValue, { color: displayColor }]}> 
            {formatMetricNumber(displayValue, config.precision)}<Text style={styles.unit}> {config.unit}</Text>
          </Text>
        </View>
        <View style={styles.historyChartMeta}>
          <Text style={styles.historyChartRange}>RANGE</Text>
          <Text style={styles.historyChartRangeValue}>
            {formatMetricNumber(minValue, config.precision)} - {formatMetricNumber(maxValue, config.precision)}
          </Text>
          <Text style={styles.historySelectedTime}>{formatHistoryTime(displayTime)}</Text>
        </View>
      </View>

      <View style={styles.chartPlot}>
        <View style={styles.chartGridLineTop} />
        <View style={styles.chartGridLineMiddle} />
        {visibleSamples.length === 0 ? (
          <Text style={styles.emptyHistoryText}>NO HISTORY</Text>
        ) : (
          visibleSamples.map((sample, index) => {
            const value = sample[config.key];
            const barHeight: `${number}%` = typeof value === 'number' && Number.isFinite(value)
              ? `${Math.max(2, Math.round((value / chartMax) * 100))}%`
              : '2%';
            const isSelected = selectedIndex === index;
            const barColor = getHealthyColorForHistoryValue(config.key, value, config.color);

            return (
              <TouchableOpacity
                key={`${sample.fetched_at}-${config.key}-${index}`}
                activeOpacity={0.75}
                onPress={() => setSelectedIndex((currentIndex) => currentIndex === index ? null : index)}
                style={[
                  styles.chartBar,
                  {
                    height: barHeight,
                    backgroundColor: barColor,
                    opacity: typeof value === 'number' ? (isSelected ? 1 : 0.78) : 0.35,
                    borderColor: isSelected ? '#ffffff' : 'transparent',
                  },
                ]}
                accessibilityRole="button"
                accessibilityLabel={`${config.label} ${formatMetricNumber(value, config.precision)} ${config.unit} at ${formatHistoryTime(sample.fetched_at)}`}
                accessibilityState={{ selected: isSelected }}
              />
            );
          })
        )}
      </View>

      <View style={styles.historyTimeRow}>
        <Text style={styles.historyTimeText}>{formatHistoryTime(visibleSamples[0]?.fetched_at)}</Text>
        <Text style={styles.historyTimeText}>WINDOW {currentWindow + 1} OF {totalWindows}</Text>
        <Text style={styles.historyTimeText}>{formatHistoryTime(visibleSamples[visibleSamples.length - 1]?.fetched_at)}</Text>
      </View>

      <View style={styles.historyNavigator}>
        <TouchableOpacity
          style={[styles.historyNavButton, !canPageOlder && styles.historyNavButtonDisabled]}
          disabled={!canPageOlder}
          onPress={showOlderWindow}
        >
          <Ionicons name="chevron-back" size={26} color={canPageOlder ? '#7ef2d0' : '#333333'} />
        </TouchableOpacity>

        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.historyScrollbarContent}
          style={styles.historyScrollbar}
        >
          {Array.from({ length: totalWindows }).map((_, index) => {
            const isActiveWindow = index === currentWindow;
            return (
              <TouchableOpacity
                key={`history-window-${index}`}
                style={[styles.historyScrollbarSegment, isActiveWindow && styles.historyScrollbarSegmentActive]}
                onPress={() => showWindow(index)}
              />
            );
          })}
        </ScrollView>

        <TouchableOpacity
          style={[styles.historyNavButton, !canPageNewer && styles.historyNavButtonDisabled]}
          disabled={!canPageNewer}
          onPress={showNewerWindow}
        >
          <Ionicons name="chevron-forward" size={26} color={canPageNewer ? '#7ef2d0' : '#333333'} />
        </TouchableOpacity>
      </View>
    </View>
  );
}

export default function Index() {
  const [phantomState, setPhantomState] = useState<PhantomState>(DEFAULT_PHANTOM);
  const [sensorMetrics, setSensorMetrics] = useState<SensorMetrics>(DEFAULT_SENSOR);
  const [loading, setLoading] = useState<string | null>(null);
  const [initialFetching, setInitialFetching] = useState<boolean>(true);
  const [indoorMetrics, setIndoorMetrics] = useState<EnvironmentalSensor | null>(null);
  const [outdoorMetrics, setOutdoorMetrics] = useState<EnvironmentalSensor | null>(null);
  const [historySamples, setHistorySamples] = useState<HistorySample[]>([]);
  const [activeHistoryMetric, setActiveHistoryMetric] = useState<HistoryMetricKey | null>(null);
  const [controlsLocked, setControlsLocked] = useState(true);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
  const [activeView, setActiveView] = useState<AppView>('home');
  const [homeTab, setHomeTab] = useState<HomeTab>('sensors');
  const [menuOpen, setMenuOpen] = useState(false);
  const [automationLog, setAutomationLog] = useState<string[]>([]);
  const [logAvailable, setLogAvailable] = useState(true);
  const [logLoading, setLogLoading] = useState(false);
  const [diagnosticsTab, setDiagnosticsTab] = useState<DiagnosticsTab>('logs');
  const [phantomStateHistory, setPhantomStateHistory] = useState<PhantomStateHistoryEntry[]>([]);
  const [stateHistoryPage, setStateHistoryPage] = useState(1);
  const [stateHistoryTotal, setStateHistoryTotal] = useState(0);
  const [stateHistoryAvailable, setStateHistoryAvailable] = useState(true);
  const [stateHistoryLoading, setStateHistoryLoading] = useState(false);
  const [stateRuntime, setStateRuntime] = useState<PhantomStateRuntimeResponse | null>(null);
  const [stateRuntimeAvailable, setStateRuntimeAvailable] = useState(true);
  const [stateRuntimeLoading, setStateRuntimeLoading] = useState(false);
  const [fontsLoaded] = useFonts({ Phantom: require('../../assets/fonts/Phantom.ttf') });
  const hourlyConsumptionEstimate = stateRuntime ? getAverageHourlyConsumption(stateRuntime) : null;

  useEffect(() => {
    fetchState();
    fetchHistory();
    const interval = setInterval(() => {
      fetchState();
      fetchHistory();
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (controlsLocked) return;

    const relockTimeout = setTimeout(() => setControlsLocked(true), 60000);
    return () => clearTimeout(relockTimeout);
  }, [controlsLocked]);

  const fetchState = async () => {
    try {
      const res = await fetch(`${API_URL}/state`);
      if (res.ok) {
        const data: CombinedState = await res.json();
        setPhantomState(data.phantom);
        setSensorMetrics(data.sensor);
        setIndoorMetrics(data.indoor ?? null);
        setOutdoorMetrics(data.outdoor ?? null);
        setLastUpdatedAt(new Date());
      }
    } catch (err) {
      console.error("Failed to sync initial state:", err);
    } finally {
      setInitialFetching(false);
    }
  };

  const fetchHistory = async () => {
    try {
      const res = await fetch(`${API_URL}/history?limit=${HISTORY_LIMIT}`);
      if (res.ok) {
        const data: HistoryResponse = await res.json();
        setHistorySamples(data.history ?? []);
      }
    } catch (err) {
      console.error("Failed to fetch sensor history:", err);
    }
  };

  const fetchAutomationLog = async () => {
    setLogLoading(true);
    try {
      const res = await fetch(`${API_URL}/logs/automation?lines=160`);
      if (!res.ok) throw new Error(`Log request failed with HTTP status ${res.status}`);
      const data: AutomationLogResponse = await res.json();
      setAutomationLog(data.lines ?? []);
      setLogAvailable(data.available);
    } catch (err) {
      console.error('Failed to fetch automation log:', err);
      setLogAvailable(false);
    } finally {
      setLogLoading(false);
    }
  };

  const fetchPhantomStateHistory = async (page = stateHistoryPage) => {
    setStateHistoryLoading(true);
    try {
      const res = await fetch(`${API_URL}/phantom-history?page=${page}&page_size=${PHANTOM_HISTORY_PAGE_SIZE}`);
      if (!res.ok) throw new Error(`State history request failed with HTTP status ${res.status}`);
      const data: PhantomStateHistoryResponse = await res.json();
      const history = Array.isArray(data.history) ? data.history : [];
      setPhantomStateHistory(history);
      setStateHistoryPage(typeof data.page === 'number' && Number.isInteger(data.page) ? data.page : 1);
      setStateHistoryTotal(typeof data.total === 'number' && Number.isFinite(data.total) ? data.total : history.length);
      setStateHistoryAvailable(true);
    } catch (err) {
      console.error('Failed to fetch Phantom state history:', err);
      setStateHistoryAvailable(false);
    } finally {
      setStateHistoryLoading(false);
    }
  };

  const navigateStateHistory = (page: number) => {
    const totalPages = Math.ceil(stateHistoryTotal / PHANTOM_HISTORY_PAGE_SIZE);
    if (page < 1 || page > totalPages || page === stateHistoryPage) return;
    setStateHistoryPage(page);
    fetchPhantomStateHistory(page);
  };

  const fetchStateRuntime = async () => {
    setStateRuntimeLoading(true);
    try {
      const res = await fetch(`${API_URL}/phantom-runtime`);
      if (!res.ok) throw new Error(`State runtime request failed with HTTP status ${res.status}`);
      setStateRuntime(await res.json());
      setStateRuntimeAvailable(true);
    } catch (err) {
      console.error('Failed to fetch Phantom state runtime:', err);
      setStateRuntimeAvailable(false);
    } finally {
      setStateRuntimeLoading(false);
    }
  };

  const refreshDiagnosticsTab = (tab = diagnosticsTab) => {
    if (tab === 'logs') fetchAutomationLog();
    else if (tab === 'state_history') fetchPhantomStateHistory();
    else fetchStateRuntime();
  };

  const sendCommand = async (actionKey: string, payload?: object) => {
    setLoading(actionKey);
    try {
      const res = await fetch(`${API_URL}/command/${actionKey}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload ? JSON.stringify(payload) : undefined,
      });

      if (!res.ok) {
        throw new Error(`Server returned HTTP status ${res.status}`);
      }

      const updatedData: CombinedState = await res.json();
      setPhantomState(updatedData.phantom);
      setSensorMetrics(updatedData.sensor);
      setIndoorMetrics(updatedData.indoor ?? null);
      setOutdoorMetrics(updatedData.outdoor ?? null);
    } catch (err) {
      console.error(`Error executing action ${actionKey}:`, err);
      Alert.alert("API Error", "Unable to communicate with Phantom Controller backend.");
    } finally {
      setLoading(null);
    }
  };

  const buttons = [
    {
      label: phantomState.automation_enabled ? "AUTO (ON)" : "AUTO (OFF)",
      key: "TOGGLE_AUTO",
      color: phantomState.automation_enabled ? "#27ae60" : "#333333",
      icon: "hardware-chip-outline"
    },
    { label: "RESET", key: "RESET", color: "#4a5568", icon: "refresh-outline" },
    { label: controlsLocked ? "UNLOCK" : "LOCK", key: "TOGGLE_LOCK", color: controlsLocked ? "#27ae60" : "#333333", icon: "key-outline" },
  ];

  const getModeGlyph = (mode: PhantomState['mode']): PhantomGlyphName | null => {
    switch (mode) {
      case 'AUTO': return 'auto';
      case 'SLEEP': return 'monitor';
      case 'MANUAL': return 'manual';
      default: return 'auto';
    }
  };

  const getFluxGlyph = (flux: PhantomState['flux']): PhantomGlyphName | null => {
    switch (flux) {
      case 'NORTH_SOUTH': return 'master_slave';
      case 'SOUTH_NORTH': return 'slave_master';
      case 'INTAKE': return 'insert';
      case 'EXTRACT': return 'evac';
      default: return null;
    }
  };

  const getButtonPhantomGlyph = (buttonKey: string): PhantomGlyphName | null => {
    switch (buttonKey) {
      case 'BOOST': return 'temp_evac';
      case 'NIGHT': return 'night';
      case 'SPEED': return 'fan';
      case 'MODE': return getModeGlyph(phantomState.mode) ?? 'home';
      case 'FLUX': return 'home';
      case 'HUMIDITY': return 'humidity';
      default: return null;
    }
  };

  const formatBatteryValue = (battery?: string | number) => {
    if (battery === undefined || battery === null) return '--';
    if (typeof battery === 'number') return `${battery}%`;
    return String(battery).toUpperCase();
  };

  const getBatteryIcon = (battery?: string | number) => {
    if (typeof battery === 'number') {
      if (battery > 60) return "battery-high";
      if (battery > 20) return "battery-medium";
      return "battery-low";
    }
    if (typeof battery === 'string') {
      const lower = battery.toLowerCase();
      if (lower === 'high') return "battery-high";
      if (lower === 'medium') return "battery-medium";
      if (lower === 'low') return "battery-low";
    }
    return "battery-unknown";
  };

  const getBatteryColor = (battery?: string | number) => {
    if (battery === undefined || battery === null) return "#6c757d";
    if (typeof battery === 'number') {
      if (battery > 20) return "#00ffcc";
      return "#e74c3c";
    }
    if (typeof battery === 'string') {
      return battery.toLowerCase() === 'low' ? "#e74c3c" : "#00ffcc";
    }
    return "#6c757d";
  };

  const getCO2Color = (ppm: number) => {
    if (ppm < 800) return "#00ffcc";
    if (ppm < 1200) return "#f39c12";
    return "#e74c3c";
  };

  const getTempColor = (temp: number) => {
    if (temp >= 18 && temp <= 24) return "#00ffcc";
    if (temp >= 15 && temp <= 28) return "#f39c12";
    return "#e74c3c";
  };

  const getHumidityColor = (hum: number) => {
    if (hum >= 30 && hum <= 50) return "#00ffcc";
    if (hum >= 25 && hum <= 60) return "#f39c12";
    return "#e74c3c";
  };

  const getPMColor = (pm: number) => {
    if (pm < 12) return "#00ffcc";
    if (pm < 35.4) return "#a8e6cf";
    if (pm < 55.4) return "#f39c12";
    return "#e74c3c";
  };

  const getTVOCColor = (tvoc: number) => {
    if (tvoc < 0.3) return "#00ffcc";
    if (tvoc < 1.0) return "#f39c12";
    return "#e74c3c";
  };

  const getFormaldehyteColor = (hcho: number) => {
    if (hcho < 0.05) return "#00ffcc";
    if (hcho < 0.1) return "#f39c12";
    return "#e74c3c";
  };

  const openHistoryMetric = (metricKey: HistoryMetricKey) => {
    setActiveHistoryMetric((currentMetric) => currentMetric === metricKey ? null : metricKey);
  };

  const activeHistoryConfig = activeHistoryMetric ? getHistoryChartConfig(activeHistoryMetric) : null;
  const co2Status = getCO2Status(sensorMetrics.co2_ppm);
  const updateLabel = lastUpdatedAt ? `Updated ${lastUpdatedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Waiting for sensor';
  const viewTitles: Record<AppView, string> = {
    home: 'Home air, made clear.',
    diagnostics: 'System diagnostics.',
  };
  const speedControlEnabled = !phantomState.automation_enabled
    && (phantomState.mode === 'MANUAL' || phantomState.flux !== 'NONE');
  const humidityControlEnabled = !phantomState.automation_enabled
    && (phantomState.mode === 'AUTO' || phantomState.mode === 'SLEEP' || phantomState.night);
  const speedStatusActive = phantomState.mode === 'MANUAL' || phantomState.flux !== 'NONE';
  const humidityStatusActive = phantomState.mode === 'AUTO' || phantomState.mode === 'SLEEP';
  const modeLabel = phantomState.mode === 'NONE' ? 'Direct airflow' : phantomState.mode;
  const fluxLabel = {
    NONE: 'None',
    NORTH_SOUTH: 'Master slave',
    SOUTH_NORTH: 'Slave master',
    INTAKE: 'Intake',
    EXTRACT: 'Extract',
  }[phantomState.flux];
  const modeAirflowCycle = phantomState.mode !== 'NONE' && phantomState.flux === 'NONE';
  const airflowStatusLabel = modeAirflowCycle ? 'Alternative' : fluxLabel;
  const modeClickable = loading === null && !controlsLocked && !phantomState.automation_enabled;
  const speedClickable = loading === null && !controlsLocked && speedControlEnabled;
  const humidityClickable = loading === null && !controlsLocked && humidityControlEnabled;
  const fluxClickable = loading === null && !controlsLocked && !phantomState.automation_enabled;
  const nightClickable = fluxClickable;
  const boostClickable = fluxClickable;

  if (!fontsLoaded || initialFetching) {
    return (
      <SafeAreaView style={[styles.container, styles.loadingScreen]}>
        <Image
          source={require('../../assets/images/phantom-mark.png')}
          style={styles.loadingMark}
          contentFit="contain"
        />
        <Text style={styles.loadingBrand}>NOVINGAIR PHANTOM</Text>
        <ActivityIndicator size="small" color="#7ef2d0" />
        <Text style={styles.loadingMessage}>Connecting to backend...</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <View style={styles.appHeader}>
          <View>
            <Text style={styles.eyebrow}>NOVINGAIR</Text>
            <Text style={styles.title}>{viewTitles[activeView]}</Text>
          </View>
          <TouchableOpacity style={styles.menuButton} onPress={() => setMenuOpen(true)} accessibilityRole="button" accessibilityLabel="Open navigation menu">
            <Ionicons name="menu" size={24} color="#7ef2d0" />
          </TouchableOpacity>
        </View>
        <Text style={styles.updatedText}>{updateLabel} · Phantom {phantomState.mode.toLowerCase()}</Text>

        <View style={[styles.homeTabs, activeView !== 'home' && styles.hiddenView]} accessibilityRole="tablist">
          <TouchableOpacity
            style={[styles.homeTab, homeTab === 'sensors' && styles.homeTabActive]}
            onPress={() => setHomeTab('sensors')}
            accessibilityRole="tab"
            accessibilityState={{ selected: homeTab === 'sensors' }}
            accessibilityLabel="Air quality and sensors"
          >
            <Ionicons name="analytics-outline" size={17} color={homeTab === 'sensors' ? '#7ef2d0' : '#657673'} />
            <Text style={[styles.homeTabText, homeTab === 'sensors' && styles.homeTabTextActive]}>Sensors</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.homeTab, homeTab === 'remote' && styles.homeTabActive]}
            onPress={() => setHomeTab('remote')}
            accessibilityRole="tab"
            accessibilityState={{ selected: homeTab === 'remote' }}
            accessibilityLabel="Phantom remote controls"
          >
            <Ionicons name="game-controller-outline" size={17} color={homeTab === 'remote' ? '#7ef2d0' : '#657673'} />
            <Text style={[styles.homeTabText, homeTab === 'remote' && styles.homeTabTextActive]}>Remote</Text>
          </TouchableOpacity>
        </View>

        {/* --- AIR QUALITY MONITOR PANEL --- */}
        <View style={[styles.sensorCard, (activeView !== 'home' || homeTab !== 'sensors') && styles.hiddenView]}>
          <View style={styles.cardHeader}>
            <View style={styles.indicatorBlock}>
              <MaterialCommunityIcons name="molecule-co2" size={24} color={getCO2Color(sensorMetrics.co2_ppm)} />
              <Text style={styles.cardHeaderTitle}>AIR DETECTOR</Text>
            </View>
            <View style={styles.indicatorBlock}>
              <MaterialCommunityIcons
                name={getBatteryIcon(sensorMetrics.battery_pct)}
                size={18}
                color={sensorMetrics.online ? getBatteryColor(sensorMetrics.battery_pct) : "#e74c3c"}
              />
              <Text style={styles.statusText}>
                {sensorMetrics.online ? `${sensorMetrics.battery_pct}%` : 'OFFLINE'}
              </Text>
            </View>
          </View>

          <View style={styles.airHero}>
            <View style={styles.airHeroCopy}>
              <Text style={styles.sectionEyebrow}>AIR NOW</Text>
              <Text style={styles.airStatus}>{co2Status.label}</Text>
              <Text style={styles.airStatusDetail}>{co2Status.detail}</Text>
            </View>
            <View style={styles.co2HeroValue}>
              <Text style={[styles.co2HeroNumber, { color: co2Status.color }]}>{formatMetricNumber(sensorMetrics.co2_ppm)}</Text>
              <Text style={styles.co2HeroUnit}>PPM CO2</Text>
            </View>
          </View>

          <View style={styles.metricsGrid}>
            <TouchableOpacity
              style={[styles.metricItem, activeHistoryMetric === 'co2_ppm' && styles.metricItemActive]}
              onPress={() => openHistoryMetric('co2_ppm')}
              accessibilityRole="button"
              accessibilityLabel={`CO2 ${sensorMetrics.co2_ppm} parts per million`}
              accessibilityHint="Opens CO2 history"
            >
              <Text style={styles.metricLabel}>CO2</Text>
              <Text style={[styles.metricValue, { color: getCO2Color(sensorMetrics.co2_ppm) }]}>
                {sensorMetrics.co2_ppm}<Text style={styles.unit}> ppm</Text>
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.metricItem, activeHistoryMetric === 'temperature_c' && styles.metricItemActive]}
              onPress={() => openHistoryMetric('temperature_c')}
              accessibilityRole="button"
              accessibilityLabel={`Temperature ${sensorMetrics.temperature_c} degrees Celsius`}
              accessibilityHint="Opens temperature history"
            >
              <Text style={styles.metricLabel}>TEMP</Text>
              <Text style={[styles.metricValue, { color: getTempColor(sensorMetrics.temperature_c) }]}>
                {sensorMetrics.temperature_c}<Text style={styles.unit}> °C</Text>
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.metricItem, activeHistoryMetric === 'humidity_pct' && styles.metricItemActive]}
              onPress={() => openHistoryMetric('humidity_pct')}
              accessibilityRole="button"
              accessibilityLabel={`Humidity ${sensorMetrics.humidity_pct} percent`}
              accessibilityHint="Opens humidity history"
            >
              <Text style={styles.metricLabel}>HUMIDITY</Text>
              <Text style={[styles.metricValue, { color: getHumidityColor(sensorMetrics.humidity_pct) }]}>
                {sensorMetrics.humidity_pct}<Text style={styles.unit}> %</Text>
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.metricItem, activeHistoryMetric === 'pm1_ugm3' && styles.metricItemActive]}
              onPress={() => openHistoryMetric('pm1_ugm3')}
            >
              <Text style={styles.metricLabel}>PM1.0</Text>
              <Text style={[styles.metricValue, { color: getPMColor(sensorMetrics.pm1_ugm3) }]}>
                {sensorMetrics.pm1_ugm3}<Text style={styles.unit}> µg/m³</Text>
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.metricItem, activeHistoryMetric === 'pm25_ugm3' && styles.metricItemActive]}
              onPress={() => openHistoryMetric('pm25_ugm3')}
              accessibilityRole="button"
              accessibilityLabel={`PM2.5 ${sensorMetrics.pm25_ugm3} micrograms per cubic meter`}
              accessibilityHint="Opens PM2.5 history"
            >
              <Text style={styles.metricLabel}>PM2.5</Text>
              <Text style={[styles.metricValue, { color: getPMColor(sensorMetrics.pm25_ugm3) }]}>
                {sensorMetrics.pm25_ugm3}<Text style={styles.unit}> µg/m³</Text>
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.metricItem, activeHistoryMetric === 'pm10_ugm3' && styles.metricItemActive]}
              onPress={() => openHistoryMetric('pm10_ugm3')}
            >
              <Text style={styles.metricLabel}>PM10</Text>
              <Text style={[styles.metricValue, { color: getPMColor(sensorMetrics.pm10_ugm3) }]}>
                {sensorMetrics.pm10_ugm3}<Text style={styles.unit}> µg/m³</Text>
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.metricItem, activeHistoryMetric === 'voc_mgm3' && styles.metricItemActive]}
              onPress={() => openHistoryMetric('voc_mgm3')}
            >
              <Text style={styles.metricLabel}>TVOC</Text>
              <Text style={[styles.metricValue, { color: getTVOCColor(sensorMetrics.voc_mgm3) }]}>
                {sensorMetrics.voc_mgm3}<Text style={styles.unit}> mg/m³</Text>
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.metricItem, activeHistoryMetric === 'ch2o_mgm3' && styles.metricItemActive]}
              onPress={() => openHistoryMetric('ch2o_mgm3')}
            >
              <Text style={styles.metricLabel}>HCHO</Text>
              <Text style={[styles.metricValue, { color: getFormaldehyteColor(sensorMetrics.ch2o_mgm3) }]}>
                {sensorMetrics.ch2o_mgm3}<Text style={styles.unit}> mg/m³</Text>
              </Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* --- ZIGBEE SENSORS PANEL --- */}
        <View style={[styles.zigbeeContainer, (activeView !== 'home' || homeTab !== 'sensors') && styles.hiddenView]}>
          {/* Indoor Sensor Box */}
          <View style={styles.zigbeeCard}>
            <View style={styles.zigbeeCardHeader}>
              <View style={styles.indicatorBlock}>
                <Ionicons name="home-outline" size={14} color="#8e9aaf" />
                <Text style={styles.zigbeeCardTitle}>INDOOR</Text>
              </View>
              <View style={styles.indicatorBlock}>
                <MaterialCommunityIcons
                  name={getBatteryIcon(indoorMetrics?.battery)}
                  size={14}
                  color={getBatteryColor(indoorMetrics?.battery)}
                />
                <Text style={styles.zigbeeBatteryText}>
                  {formatBatteryValue(indoorMetrics?.battery)}
                </Text>
              </View>
            </View>
            <View style={styles.zigbeeMetricsRow}>
              <TouchableOpacity
                style={[styles.zigbeeMetric, activeHistoryMetric === 'indoor_temperature_c' && styles.metricItemActive]}
                onPress={() => openHistoryMetric('indoor_temperature_c')}
              >
                <Text style={styles.metricLabel}>TEMP</Text>
                <Text style={[styles.metricValue, { color: indoorMetrics?.temperature_c !== undefined ? getTempColor(indoorMetrics.temperature_c) : '#6c757d' }]}>
                  {indoorMetrics?.temperature_c !== undefined ? indoorMetrics.temperature_c : '--'}
                  <Text style={styles.unit}> °C</Text>
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.zigbeeMetric, activeHistoryMetric === 'indoor_humidity_pct' && styles.metricItemActive]}
                onPress={() => openHistoryMetric('indoor_humidity_pct')}
              >
                <Text style={styles.metricLabel}>HUM</Text>
                <Text style={[styles.metricValue, { color: indoorMetrics?.humidity_pct !== undefined ? getHumidityColor(indoorMetrics.humidity_pct) : '#6c757d' }]}>
                  {indoorMetrics?.humidity_pct !== undefined ? indoorMetrics.humidity_pct : '--'}
                  <Text style={styles.unit}> %</Text>
                </Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* Outdoor Sensor Box */}
          <View style={styles.zigbeeCard}>
            <View style={styles.zigbeeCardHeader}>
              <View style={styles.indicatorBlock}>
                <Ionicons name="leaf-outline" size={14} color="#8e9aaf" />
                <Text style={styles.zigbeeCardTitle}>OUTDOOR</Text>
              </View>
              <View style={styles.indicatorBlock}>
                <MaterialCommunityIcons
                  name={getBatteryIcon(outdoorMetrics?.battery)}
                  size={14}
                  color={getBatteryColor(outdoorMetrics?.battery)}
                />
                <Text style={styles.zigbeeBatteryText}>
                  {formatBatteryValue(outdoorMetrics?.battery)}
                </Text>
              </View>
            </View>
            <View style={styles.zigbeeMetricsRow}>
              <TouchableOpacity
                style={[styles.zigbeeMetric, activeHistoryMetric === 'outdoor_temperature_c' && styles.metricItemActive]}
                onPress={() => openHistoryMetric('outdoor_temperature_c')}
              >
                <Text style={styles.metricLabel}>TEMP</Text>
                <Text style={[styles.metricValue, { color: outdoorMetrics?.temperature_c !== undefined ? getTempColor(outdoorMetrics.temperature_c) : '#6c757d' }]}>
                  {outdoorMetrics?.temperature_c !== undefined ? outdoorMetrics.temperature_c : '--'}
                  <Text style={styles.unit}> °C</Text>
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.zigbeeMetric, activeHistoryMetric === 'outdoor_humidity_pct' && styles.metricItemActive]}
                onPress={() => openHistoryMetric('outdoor_humidity_pct')}
              >
                <Text style={styles.metricLabel}>HUM</Text>
                <Text style={[styles.metricValue, { color: outdoorMetrics?.humidity_pct !== undefined ? getHumidityColor(outdoorMetrics.humidity_pct) : '#6c757d' }]}>
                  {outdoorMetrics?.humidity_pct !== undefined ? outdoorMetrics.humidity_pct : '--'}
                  <Text style={styles.unit}> %</Text>
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>

        <View style={[styles.currentStatusCard, (activeView !== 'home' || homeTab !== 'sensors') && styles.hiddenView]}>
          <View style={styles.currentStatusHeader}>
            <View>
              <Text style={styles.sectionEyebrow}>CURRENT STATUS</Text>
              <Text style={styles.currentStatusTitle}>Phantom is {phantomState.automation_enabled ? 'running automatically' : 'under manual control'}</Text>
            </View>
            <View style={[styles.automationBadge, phantomState.automation_enabled ? styles.automationBadgeOn : styles.automationBadgeOff]}>
              <View style={[styles.automationDot, { backgroundColor: phantomState.automation_enabled ? '#00d9ae' : '#657673' }]} />
              <Text style={styles.automationBadgeText}>AUTO {phantomState.automation_enabled ? 'ON' : 'OFF'}</Text>
            </View>
          </View>

          <View style={styles.currentStatusGrid}>
            <View style={styles.currentStatusItem}>
              <Text style={styles.currentStatusLabel}>MODE</Text>
              <Text style={styles.currentStatusValue}>{modeLabel}</Text>
            </View>
            <View style={styles.currentStatusItem}>
              <Text style={styles.currentStatusLabel}>AIRFLOW</Text>
              <Text style={styles.currentStatusValue}>{airflowStatusLabel}</Text>
            </View>
            {speedStatusActive && (
              <View style={styles.currentStatusItem}>
                <Text style={styles.currentStatusLabel}>SPEED</Text>
                <Text style={styles.currentStatusValue}>Level {phantomState.speed}</Text>
              </View>
            )}
            {humidityStatusActive && (
              <View style={styles.currentStatusItem}>
                <Text style={styles.currentStatusLabel}>HUMIDITY</Text>
                <Text style={styles.currentStatusValue}>Level {phantomState.humidity}</Text>
              </View>
            )}
          </View>
        </View>

        {/* --- HRV LCD STATUS SCREEN --- */}
        <View style={[styles.lcdScreen, (activeView !== 'home' || homeTab !== 'remote') && styles.hiddenView]}>
          <Text style={styles.lcdHeaderTitle}>PHANTOM UNIT STATUS</Text>
          <View style={styles.controlNotice}>
            <Ionicons
              name={controlsLocked ? 'lock-closed-outline' : phantomState.automation_enabled ? 'sparkles-outline' : 'create-outline'}
              size={16}
              color={controlsLocked ? '#f4b860' : '#7ef2d0'}
            />
            <Text style={styles.controlNoticeText}>
              {controlsLocked
                ? 'Locked for safety · Unlock to adjust.'
                : phantomState.automation_enabled
                  ? 'Automation is managing the Phantom unit.'
                  : 'Manual control is active.'}
            </Text>
          </View>

          <View style={styles.lcdRow}>
            <TouchableOpacity
              style={[
                styles.statusBox,
                phantomState.mode !== 'NONE' && (phantomState.automation_enabled && !controlsLocked
                  ? styles.statusBoxAutoHighlighted
                  : styles.statusBoxHighlighted),
                (phantomState.mode === 'NONE' || controlsLocked) && styles.statusBoxDisabled,
                phantomState.mode === 'NONE' && styles.statusBoxDisabledBorder,
              ]}
              onPress={() => sendCommand('MODE')}
              disabled={loading !== null || controlsLocked || phantomState.automation_enabled}
              accessibilityRole="button"
              accessibilityLabel={`Mode ${phantomState.mode.toLowerCase()}`}
              accessibilityState={{ disabled: !modeClickable, selected: phantomState.mode !== 'NONE' }}
            >
              {getModeGlyph(phantomState.mode) ? (
                <PhantomGlyph
                  name={getModeGlyph(phantomState.mode)!}
                  color={modeClickable ? '#00ffcc' : '#444'}
                />
              ) : (
                <MaterialCommunityIcons name="minus-circle-outline" size={18} color="#444" />
              )}
              <Text style={[styles.controlLabel, !modeClickable && styles.controlLabelDisabled]}>{phantomState.mode}</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[
              styles.statusBox,
              speedStatusActive && (phantomState.automation_enabled && !controlsLocked
                ? styles.statusBoxAutoHighlighted
                : styles.statusBoxHighlighted),
              (!speedStatusActive || controlsLocked) && styles.statusBoxDisabled,
              !speedStatusActive && styles.statusBoxDisabledBorder,
              ]}
              onPress={() => sendCommand('SPEED')}
              disabled={loading !== null || controlsLocked || !speedControlEnabled}
              accessibilityRole="button"
              accessibilityLabel={`Fan speed ${phantomState.speed} of 3`}
              accessibilityState={{ disabled: !speedClickable, selected: speedStatusActive }}
            >
              <PhantomLevelGlyphs
                name="fan"
                level={phantomState.speed}
                color={speedClickable ? "#00ffcc" : "#444"}
              />
              <Text style={[styles.controlLabel, !speedClickable && styles.controlLabelDisabled]}>SPEED {phantomState.speed}</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[
              styles.statusBox,
              humidityStatusActive && (phantomState.automation_enabled && !controlsLocked
                ? styles.statusBoxAutoHighlighted
                : styles.statusBoxHighlighted),
              (!humidityStatusActive || controlsLocked) && styles.statusBoxDisabled,
              !humidityStatusActive && styles.statusBoxDisabledBorder,
              ]}
              onPress={() => sendCommand('HUMIDITY')}
              disabled={loading !== null || controlsLocked || !humidityControlEnabled}
              accessibilityRole="button"
              accessibilityLabel={`Humidity target ${phantomState.humidity} of 3`}
              accessibilityState={{ disabled: !humidityClickable, selected: humidityStatusActive }}
            >
              <PhantomLevelGlyphs
                name="humidity"
                level={phantomState.humidity}
                color={humidityClickable ? "#00ffcc" : "#444"}
              />
              <Text style={[styles.controlLabel, !humidityClickable && styles.controlLabelDisabled]}>HUMIDITY {phantomState.humidity}</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.lcdRow}>
            <TouchableOpacity
              style={[
                styles.statusBox,
                phantomState.flux !== 'NONE' && (phantomState.automation_enabled && !controlsLocked
                  ? styles.statusBoxAutoHighlighted
                  : styles.statusBoxHighlighted),
                (phantomState.flux === 'NONE' || controlsLocked) && styles.statusBoxDisabled,
                phantomState.flux === 'NONE' && styles.statusBoxDisabledBorder,
              ]}
              onPress={() => sendCommand('FLUX')}
              disabled={loading !== null || controlsLocked || phantomState.automation_enabled}
              accessibilityRole="button"
              accessibilityLabel={`Airflow ${phantomState.flux.toLowerCase()}`}
              accessibilityState={{ disabled: !fluxClickable, selected: phantomState.flux !== 'NONE' }}
            >
              {getFluxGlyph(phantomState.flux) ? (
                <PhantomGlyph
                  name={getFluxGlyph(phantomState.flux)!}
                  color={fluxClickable ? '#00ffcc' : '#444'}
                />
              ) : (
                <MaterialCommunityIcons name="minus-circle-outline" size={18} color="#444" />
              )}
              <Text style={[styles.controlLabel, !fluxClickable && styles.controlLabelDisabled]}>AIRFLOW</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[
                styles.statusBox,
                phantomState.night && (phantomState.automation_enabled && !controlsLocked
                  ? styles.statusBoxAutoHighlighted
                  : styles.statusBoxHighlighted),
                (!phantomState.night || controlsLocked) && styles.statusBoxDisabled,
                !phantomState.night && styles.statusBoxDisabledBorder,
              ]}
              onPress={() => sendCommand('NIGHT')}
              disabled={loading !== null || controlsLocked || phantomState.automation_enabled}
              accessibilityRole="button"
              accessibilityLabel="Night mode"
              accessibilityState={{ disabled: !nightClickable, selected: phantomState.night }}
            >
              <PhantomGlyph name="night" color={nightClickable ? "#00ffcc" : "#444"} />
              <Text style={[styles.controlLabel, !nightClickable && styles.controlLabelDisabled]}>NIGHT</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[
                styles.statusBox,
                phantomState.boost && (phantomState.automation_enabled && !controlsLocked
                  ? styles.statusBoxAutoHighlighted
                  : styles.statusBoxHighlighted),
                (!phantomState.boost || controlsLocked) && styles.statusBoxDisabled,
                !phantomState.boost && styles.statusBoxDisabledBorder,
              ]}
              onPress={() => sendCommand('BOOST')}
              disabled={loading !== null || controlsLocked || phantomState.automation_enabled}
              accessibilityRole="button"
              accessibilityLabel="Boost"
              accessibilityState={{ disabled: !boostClickable, selected: phantomState.boost }}
            >
              <PhantomGlyph name="temp_evac" color={boostClickable ? "#00ffcc" : "#444"} />
              <Text style={[styles.controlLabel, !boostClickable && styles.controlLabelDisabled]}>BOOST</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.lcdRow}>
            {buttons.map((btn) => {
              const isDisabled = loading !== null
                || (controlsLocked && btn.key !== "TOGGLE_LOCK")
                || (phantomState.automation_enabled
                  && btn.key !== "TOGGLE_AUTO"
                  && btn.key !== "RESET"
                  && btn.key !== "TOGGLE_LOCK");
              const isVisuallyDisabled = isDisabled
                || (!controlsLocked && btn.key === "TOGGLE_LOCK")
                || btn.key === "RESET"
                || (btn.key === "TOGGLE_AUTO" && !phantomState.automation_enabled);
              const isSelected = (btn.key === "TOGGLE_AUTO" && phantomState.automation_enabled)
                || (btn.key === "TOGGLE_LOCK" && controlsLocked);
              return (
                <TouchableOpacity
                  key={btn.key}
                  style={[
                    styles.statusBox,
                    { flex: 1, width: 0 },
                    isSelected && btn.key === "TOGGLE_AUTO" && phantomState.automation_enabled && !controlsLocked
                      ? styles.statusBoxHighlighted
                      : isSelected && (phantomState.automation_enabled && !controlsLocked
                      ? styles.statusBoxAutoHighlighted
                      : styles.statusBoxHighlighted),
                    isVisuallyDisabled && !isSelected && styles.statusBoxDisabledBorder,
                    isVisuallyDisabled && styles.statusBoxDisabled,
                    btn.key === "TOGGLE_AUTO" && phantomState.automation_enabled && !controlsLocked && { opacity: 1 },
                  ]}
                  onPress={() => btn.key === "TOGGLE_LOCK"
                    ? setControlsLocked((locked) => !locked)
                    : sendCommand(btn.key)}
                  disabled={isDisabled}
                  accessibilityRole="button"
                  accessibilityLabel={btn.label}
                >
                  {loading === btn.key ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <>
                      <Ionicons
                        name={btn.icon as any}
                        size={18}
                        color={!isDisabled ? '#00ffcc' : '#444'}
                      />
                      {btn.key !== "TOGGLE_LOCK" && (
                        <Text style={[styles.statusBoxLabel, controlsLocked && styles.statusBoxLabelDisabled]}>
                          {btn.label}
                        </Text>
                      )}
                    </>
                  )}
                </TouchableOpacity>
              );
            })}
          </View>
        </View>

        <View style={[styles.diagnosticsCard, activeView !== 'diagnostics' && styles.hiddenView]}>
          <View style={styles.diagnosticsHeader}>
            <View>
              <Text style={styles.sectionEyebrow}>
                {diagnosticsTab === 'logs' ? 'AUTOMATION LOG' : diagnosticsTab === 'state_history' ? 'PHANTOM STATE' : 'STATE RUNTIME'}
              </Text>
              <Text style={styles.diagnosticsTitle}>
                {diagnosticsTab === 'logs' ? 'Recent system activity' : diagnosticsTab === 'state_history' ? 'State change history' : 'Time by operating state'}
              </Text>
            </View>
            <TouchableOpacity
              style={styles.refreshButton}
              onPress={() => refreshDiagnosticsTab()}
              disabled={diagnosticsTab === 'logs' ? logLoading : diagnosticsTab === 'state_history' ? stateHistoryLoading : stateRuntimeLoading}
              accessibilityRole="button"
              accessibilityLabel={diagnosticsTab === 'logs' ? 'Refresh automation log' : diagnosticsTab === 'state_history' ? 'Refresh Phantom state history' : 'Refresh state runtime chart'}
            >
              {(diagnosticsTab === 'logs' ? logLoading : diagnosticsTab === 'state_history' ? stateHistoryLoading : stateRuntimeLoading)
                ? <ActivityIndicator size="small" color="#7ef2d0" />
                : <Ionicons name="refresh" size={18} color="#7ef2d0" />}
            </TouchableOpacity>
          </View>
          <View style={styles.diagnosticsTabs} accessibilityRole="tablist">
            <TouchableOpacity
              style={[styles.diagnosticsTab, diagnosticsTab === 'logs' && styles.diagnosticsTabActive]}
              onPress={() => setDiagnosticsTab('logs')}
              accessibilityRole="tab"
              accessibilityState={{ selected: diagnosticsTab === 'logs' }}
            >
              <Text style={[styles.diagnosticsTabText, diagnosticsTab === 'logs' && styles.diagnosticsTabTextActive]}>Logs</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.diagnosticsTab, diagnosticsTab === 'state_history' && styles.diagnosticsTabActive]}
              onPress={() => {
                setDiagnosticsTab('state_history');
                fetchPhantomStateHistory();
              }}
              accessibilityRole="tab"
              accessibilityState={{ selected: diagnosticsTab === 'state_history' }}
            >
              <Text style={[styles.diagnosticsTabText, diagnosticsTab === 'state_history' && styles.diagnosticsTabTextActive]}>State history</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.diagnosticsTab, diagnosticsTab === 'state_chart' && styles.diagnosticsTabActive]}
              onPress={() => {
                setDiagnosticsTab('state_chart');
                fetchStateRuntime();
              }}
              accessibilityRole="tab"
              accessibilityState={{ selected: diagnosticsTab === 'state_chart' }}
            >
              <Text style={[styles.diagnosticsTabText, diagnosticsTab === 'state_chart' && styles.diagnosticsTabTextActive]}>State chart</Text>
            </TouchableOpacity>
          </View>
          {diagnosticsTab === 'logs' ? (
            <>
              {!logAvailable ? (
                <Text style={styles.diagnosticsEmpty}>Automation log is unavailable.</Text>
              ) : automationLog.length === 0 ? (
                <Text style={styles.diagnosticsEmpty}>No automation entries yet.</Text>
              ) : (
                <ScrollView
                  style={styles.logScroll}
                  contentContainerStyle={styles.logScrollContent}
                  showsVerticalScrollIndicator
                  nestedScrollEnabled
                >
                  {automationLog.map((line, index) => (
                    <Text key={`${index}-${line}`} style={styles.logLine}>{formatAutomationLogLine(line)}</Text>
                  ))}
                </ScrollView>
              )}
              <Text style={styles.diagnosticsFootnote}>Showing the latest {automationLog.length} entries from logs/automation.log · Bucharest time</Text>
            </>
          ) : diagnosticsTab === 'state_history' ? (
            stateHistoryLoading ? (
              <View style={styles.stateHistoryLoading}>
                <ActivityIndicator size="small" color="#7ef2d0" />
              </View>
            ) : !stateHistoryAvailable ? (
              <Text style={styles.diagnosticsEmpty}>Phantom state history is unavailable.</Text>
            ) : phantomStateHistory.length === 0 ? (
              <Text style={styles.diagnosticsEmpty}>No Phantom state changes recorded yet.</Text>
            ) : (
            <>
              <ScrollView style={styles.stateHistoryScroll} nestedScrollEnabled showsVerticalScrollIndicator>
                <ScrollView horizontal nestedScrollEnabled showsHorizontalScrollIndicator contentContainerStyle={styles.stateHistoryTableContent}>
                  <View style={styles.stateHistoryTable}>
                    <View style={[styles.stateHistoryRow, styles.stateHistoryHeaderRow]}>
                      <Text style={[styles.stateHistoryHeaderCell, styles.stateHistoryTimeCell]}>TIME</Text>
                      <Text style={[styles.stateHistoryHeaderCell, styles.stateHistoryModeCell]}>MODE</Text>
                      <Text style={[styles.stateHistoryHeaderCell, styles.stateHistoryNumberCell]}>SPEED</Text>
                      <Text style={[styles.stateHistoryHeaderCell, styles.stateHistoryNumberCell]}>HUM</Text>
                      <Text style={[styles.stateHistoryHeaderCell, styles.stateHistoryFluxCell]}>FLUX</Text>
                      <Text style={[styles.stateHistoryHeaderCell, styles.stateHistoryFlagCell]}>NIGHT</Text>
                      <Text style={[styles.stateHistoryHeaderCell, styles.stateHistoryFlagCell]}>BOOST</Text>
                      <Text style={[styles.stateHistoryHeaderCell, styles.stateHistoryFlagCell]}>AUTO</Text>
                    </View>
                    {phantomStateHistory.map((entry) => (
                      <View key={entry.id} style={styles.stateHistoryRow}>
                        <Text style={[styles.stateHistoryCell, styles.stateHistoryTimeCell]} numberOfLines={1}>
                          {new Date(entry.created_at).toLocaleString()}
                        </Text>
                        <Text style={[styles.stateHistoryCell, styles.stateHistoryModeCell]}>{entry.state.mode ?? '--'}</Text>
                        <Text style={[styles.stateHistoryCell, styles.stateHistoryNumberCell]}>{entry.state.speed ?? '--'}</Text>
                        <Text style={[styles.stateHistoryCell, styles.stateHistoryNumberCell]}>{entry.state.humidity ?? '--'}</Text>
                        <Text style={[styles.stateHistoryCell, styles.stateHistoryFluxCell]} numberOfLines={1}>{entry.state.flux ?? '--'}</Text>
                        <Text style={[styles.stateHistoryCell, styles.stateHistoryFlagCell]}>{entry.state.night ? 'ON' : 'OFF'}</Text>
                        <Text style={[styles.stateHistoryCell, styles.stateHistoryFlagCell]}>{entry.state.boost ? 'ON' : 'OFF'}</Text>
                        <Text style={[styles.stateHistoryCell, styles.stateHistoryFlagCell]}>{entry.state.automation_enabled ? 'ON' : 'OFF'}</Text>
                      </View>
                    ))}
                  </View>
                </ScrollView>
              </ScrollView>
              <View style={styles.stateHistoryPagination}>
                <View style={styles.stateHistoryPaginationGroup}>
                  <TouchableOpacity
                    style={[styles.stateHistoryPageButton, stateHistoryPage <= 1 && styles.stateHistoryPageButtonDisabled]}
                    onPress={() => navigateStateHistory(1)}
                    disabled={stateHistoryPage <= 1 || stateHistoryLoading}
                    accessibilityRole="button"
                    accessibilityLabel="First history page"
                  >
                    <Text style={styles.stateHistoryPageText}>{'<<'}</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.stateHistoryPageButton, stateHistoryPage <= 1 && styles.stateHistoryPageButtonDisabled]}
                    onPress={() => navigateStateHistory(stateHistoryPage - 1)}
                    disabled={stateHistoryPage <= 1 || stateHistoryLoading}
                    accessibilityRole="button"
                    accessibilityLabel="Previous history page"
                  >
                    <Ionicons name="chevron-back" size={16} color={stateHistoryPage <= 1 ? '#444' : '#7ef2d0'} />
                  </TouchableOpacity>
                </View>
                <Text style={styles.stateHistoryPageIndicator}>
                  {stateHistoryPage} / {Math.max(1, Math.ceil(stateHistoryTotal / PHANTOM_HISTORY_PAGE_SIZE))}
                </Text>
                <View style={styles.stateHistoryPaginationGroup}>
                  <TouchableOpacity
                    style={[styles.stateHistoryPageButton, stateHistoryPage >= Math.ceil(stateHistoryTotal / PHANTOM_HISTORY_PAGE_SIZE) && styles.stateHistoryPageButtonDisabled]}
                    onPress={() => navigateStateHistory(stateHistoryPage + 1)}
                    disabled={stateHistoryPage >= Math.ceil(stateHistoryTotal / PHANTOM_HISTORY_PAGE_SIZE) || stateHistoryLoading}
                    accessibilityRole="button"
                    accessibilityLabel="Next history page"
                  >
                    <Ionicons name="chevron-forward" size={16} color={stateHistoryPage >= Math.ceil(stateHistoryTotal / PHANTOM_HISTORY_PAGE_SIZE) ? '#444' : '#7ef2d0'} />
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.stateHistoryPageButton, stateHistoryPage >= Math.ceil(stateHistoryTotal / PHANTOM_HISTORY_PAGE_SIZE) && styles.stateHistoryPageButtonDisabled]}
                    onPress={() => navigateStateHistory(Math.ceil(stateHistoryTotal / PHANTOM_HISTORY_PAGE_SIZE))}
                    disabled={stateHistoryPage >= Math.ceil(stateHistoryTotal / PHANTOM_HISTORY_PAGE_SIZE) || stateHistoryLoading}
                    accessibilityRole="button"
                    accessibilityLabel="Last history page"
                  >
                    <Text style={styles.stateHistoryPageText}>{'>>'}</Text>
                  </TouchableOpacity>
                </View>
              </View>
              <Text style={styles.diagnosticsFootnote} numberOfLines={1}>
                {stateHistoryTotal} state changes · newest first
              </Text>
            </>
            )
          ) : stateRuntimeLoading ? (
            <View style={styles.stateHistoryLoading}>
              <ActivityIndicator size="small" color="#7ef2d0" />
            </View>
          ) : !stateRuntimeAvailable || !stateRuntime ? (
            <Text style={styles.diagnosticsEmpty}>State runtime data is unavailable.</Text>
          ) : stateRuntime.total_seconds === 0 ? (
            <Text style={styles.diagnosticsEmpty}>No state history available to summarize yet.</Text>
          ) : (
            <View style={styles.stateRuntimeChart}>
              <View style={styles.stateRuntimeSummary}>
                <Text style={styles.stateRuntimeTotal}>{formatRuntimeDuration(stateRuntime.total_seconds)}</Text>
                <Text style={styles.stateRuntimeCaption}>recorded runtime</Text>
              </View>
              <Text style={styles.stateRuntimePeriod} numberOfLines={2}>
                Since {stateRuntime.started_at ? new Date(stateRuntime.started_at).toLocaleString() : 'unknown'}
              </Text>
              {STATE_RUNTIME_CATEGORIES.map((category) => {
                const seconds = Math.max(0, stateRuntime.durations_seconds[category.key] ?? 0);
                const percentage = stateRuntime.total_seconds > 0 ? Math.min(100, seconds / stateRuntime.total_seconds * 100) : 0;
                return (
                  <View key={category.key} style={styles.stateRuntimeRow}>
                    <View style={styles.stateRuntimeLabelRow}>
                      <View style={[styles.stateRuntimeSwatch, { backgroundColor: category.color }]} />
                      <Text style={styles.stateRuntimeLabel}>{category.label}</Text>
                      <Text style={styles.stateRuntimeValue}>{formatRuntimeDuration(seconds)} · {percentage.toFixed(1)}%</Text>
                    </View>
                    <View style={styles.stateRuntimeTrack}>
                      <View style={[styles.stateRuntimeBar, { width: `${percentage}%`, backgroundColor: category.color }]} />
                    </View>
                  </View>
                );
              })}
              <Text style={styles.diagnosticsFootnote}>
                Boost is included in Speed 3.{"\n"}Night runtime is counted separately.
              </Text>
              <View style={styles.stateEnergySummary}>
                <View style={styles.stateEnergyRow}>
                  <View style={styles.stateEnergyDetails}>
                    <Text style={styles.stateEnergyLabel}>Average hourly consumption</Text>
                    <Text style={styles.stateEnergyCaption}>
                      4 units · {hourlyConsumptionEstimate ? `based on ${formatRuntimeDuration(hourlyConsumptionEstimate.runtimeSeconds)} runtime` : 'period unavailable'}
                    </Text>
                  </View>
                  <Text style={styles.stateEnergyValue}>
                    {hourlyConsumptionEstimate ? `${(hourlyConsumptionEstimate.kwhPerHour * 1000).toFixed(1)} W` : 'Unavailable'}
                  </Text>
                </View>
                <View style={[styles.stateEnergyRow, styles.stateEnergyYearlyRow]}>
                  <View style={styles.stateEnergyDetails}>
                    <Text style={styles.stateEnergyLabel}>Estimated yearly consumption</Text>
                    <Text style={styles.stateEnergyCaption}>If this operating mix continues</Text>
                  </View>
                  <Text style={styles.stateEnergyValue}>
                    {hourlyConsumptionEstimate ? `${hourlyConsumptionEstimate.kwhPerYear.toFixed(1)} kWh/yr` : 'Unavailable'}
                  </Text>
                </View>
              </View>
              <View style={styles.statePowerBreakdown}>
                <Text style={styles.stateEnergyLabel}>Power per unit</Text>
                <View style={styles.statePowerRow}>
                  <Text style={styles.statePowerLabel}>Night</Text>
                  <Text style={styles.statePowerValue}>3.9 W</Text>
                </View>
                <View style={styles.statePowerRow}>
                  <Text style={styles.statePowerLabel}>Speed 1</Text>
                  <Text style={styles.statePowerValue}>4.2 W</Text>
                </View>
                <View style={styles.statePowerRow}>
                  <Text style={styles.statePowerLabel}>Speed 2</Text>
                  <Text style={styles.statePowerValue}>5.5 W</Text>
                </View>
                <View style={styles.statePowerRow}>
                  <Text style={styles.statePowerLabel}>Speed 3</Text>
                  <Text style={styles.statePowerValue}>6.7 W</Text>
                </View>
              </View>
            </View>
          )}
        </View>
        <View style={styles.appFooter}>
          <Text style={styles.appFooterLabel}>NOVINGAIR PHANTOM WIRELESS CONTROLLER</Text>
          <ExternalLink href="https://github.com/avra911/NovingAir-Phantom-Wireless-Controller">
            <Text style={styles.appFooterLink}>View project on GitHub</Text>
          </ExternalLink>
        </View>
      </ScrollView>

      <Modal
        visible={activeHistoryConfig !== null}
        animationType="fade"
        transparent={false}
        onRequestClose={() => setActiveHistoryMetric(null)}
      >
        {activeHistoryConfig && (
          <SafeAreaView style={styles.historyModalScreen}>
            <View style={styles.historyModalCard}>
              <View style={styles.cardHeader}>
                <View style={styles.indicatorBlock}>
                  <MaterialCommunityIcons name="chart-bar" size={22} color="#00ffcc" />
                  <Text style={styles.cardHeaderTitle}>{activeHistoryConfig.label} HISTORY</Text>
                </View>
                <TouchableOpacity style={styles.historyCloseButton} onPress={() => setActiveHistoryMetric(null)}>
                  <Ionicons name="close" size={16} color="#8e9aaf" />
                </TouchableOpacity>
              </View>
              <Text style={styles.historyChooserLabel}>SENSOR MEASURE</Text>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.historyMetricChooser}
                style={styles.historyMetricChooserScroll}
              >
                {HISTORY_CHARTS.map((chart) => {
                  const isActive = chart.key === activeHistoryMetric;
                  return (
                    <TouchableOpacity
                      key={chart.key}
                      style={[styles.historyMetricChoice, isActive && styles.historyMetricChoiceActive]}
                      onPress={() => setActiveHistoryMetric(chart.key)}
                      accessibilityRole="button"
                      accessibilityState={{ selected: isActive }}
                      accessibilityLabel={`Show ${chart.label} history`}
                    >
                      <Text style={[styles.historyMetricChoiceText, isActive && styles.historyMetricChoiceTextActive]}>
                        {chart.label}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </ScrollView>
              <MiniHistoryChart config={activeHistoryConfig} samples={historySamples} />
              <Text style={styles.historyFootnote}>{historySamples.length} stored minutes · latest {VISIBLE_CHART_SAMPLES} min shown</Text>
            </View>
          </SafeAreaView>
        )}
      </Modal>

      <Modal visible={menuOpen} transparent animationType="fade" onRequestClose={() => setMenuOpen(false)}>
        <View style={styles.menuOverlay}>
          <TouchableOpacity style={styles.menuBackdrop} onPress={() => setMenuOpen(false)} accessibilityLabel="Close navigation menu" />
          <View style={styles.menuPanel}>
            <View style={styles.menuPanelHeader}>
              <View>
                <Text style={styles.eyebrow}>NOVINGAIR</Text>
                <Text style={styles.menuTitle}>Navigate</Text>
              </View>
              <TouchableOpacity onPress={() => setMenuOpen(false)} accessibilityRole="button" accessibilityLabel="Close menu">
                <Ionicons name="close" size={22} color="#9aa9a7" />
              </TouchableOpacity>
            </View>
            {([
              ['home', 'Home', 'Air quality and sensors', 'home-outline'],
              ['diagnostics', 'Diagnostics', 'Automation and system logs', 'bug-outline'],
            ] as const).map(([view, label, detail, icon]) => (
              <TouchableOpacity
                key={view}
                style={[styles.menuItem, activeView === view && styles.menuItemActive]}
                onPress={() => {
                  setActiveView(view);
                  setMenuOpen(false);
                  if (view === 'diagnostics') {
                    refreshDiagnosticsTab();
                  }
                }}
                accessibilityRole="button"
                accessibilityState={{ selected: activeView === view }}
                accessibilityLabel={`${label}: ${detail}`}
              >
                <Ionicons name={icon} size={22} color={activeView === view ? '#7ef2d0' : '#657673'} />
                <View style={styles.menuItemCopy}>
                  <Text style={[styles.menuItemLabel, activeView === view && styles.menuItemLabelActive]}>{label}</Text>
                  <Text style={styles.menuItemDetail}>{detail}</Text>
                </View>
                {activeView === view && <View style={styles.menuActiveDot} />}
              </TouchableOpacity>
            ))}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000000' },
  loadingScreen: { alignItems: 'center', justifyContent: 'center', padding: 24, gap: 16 },
  loadingMark: { width: 112, height: 112 },
  loadingBrand: { color: '#7ef2d0', fontSize: 11, fontWeight: '800', letterSpacing: 2 },
  loadingMessage: { color: '#c4d2ce', fontSize: 13, fontWeight: '600' },
  scrollContent: { alignItems: 'center', paddingVertical: 24, paddingHorizontal: 16 },
  appHeader: {
    width: '100%',
    maxWidth: 760,
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  eyebrow: { color: '#7ef2d0', fontSize: 11, fontWeight: '800', letterSpacing: 2 },
  title: { fontSize: 25, fontWeight: '700', color: '#f4faf8', marginTop: 4 },
  connectionPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    borderWidth: 1,
    borderColor: '#1b2926',
    borderRadius: 20,
    paddingHorizontal: 11,
    paddingVertical: 7,
    marginTop: 2,
  },
  connectionDot: { width: 7, height: 7, borderRadius: 4 },
  connectionText: { color: '#9aa9a7', fontSize: 10, fontWeight: '800', letterSpacing: 1 },
  menuButton: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#1b2926',
    borderRadius: 12,
  },
  updatedText: {
    width: '100%',
    maxWidth: 760,
    color: '#657673',
    fontSize: 11,
    fontFamily: 'monospace',
    marginBottom: 16,
  },
  appFooter: {
    width: '100%',
    maxWidth: 760,
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: '#1b2926',
    marginTop: 4,
    paddingTop: 16,
    paddingBottom: 8,
    gap: 6,
  },
  appFooterLabel: { color: '#657673', fontSize: 9, fontWeight: '700', textAlign: 'center' },
  appFooterLink: { color: '#7ef2d0', fontSize: 11, fontWeight: '700', textAlign: 'center' },
  
  sensorCard: {
    width: '100%',
    maxWidth: 760,
    backgroundColor: '#0a0d0d',
    borderRadius: 18,
    padding: 18,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#1b2926',
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#222222',
    paddingBottom: 8,
  },
  cardHeaderTitle: { color: '#9aa9a7', fontSize: 12, fontWeight: 'bold', letterSpacing: 1 },
  statusText: { color: '#9aa9a7', fontSize: 11, fontFamily: 'monospace' },
  airHero: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#06241d',
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 16,
    marginBottom: 16,
  },
  airHeroCopy: { flex: 1, paddingRight: 12 },
  sectionEyebrow: { color: '#7ef2d0', fontSize: 10, fontWeight: '800', letterSpacing: 1.5, marginBottom: 5 },
  airStatus: { color: '#f4faf8', fontSize: 19, fontWeight: '700', marginBottom: 4 },
  airStatusDetail: { color: '#9aa9a7', fontSize: 11, lineHeight: 16 },
  co2HeroValue: { alignItems: 'flex-end' },
  co2HeroNumber: { fontSize: 34, fontWeight: '700', fontFamily: 'monospace' },
  co2HeroUnit: { color: '#9aa9a7', fontSize: 10, fontWeight: '800', letterSpacing: 1 },
  metricsGrid: { 
    flexDirection: 'row', 
    flexWrap: 'wrap', 
    justifyContent: 'space-between',
    rowGap: 10,
  },
  metricItem: {
    width: '24%',
    minHeight: 54,
    paddingVertical: 7,
    alignItems: 'center',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  metricItemActive: {
    borderColor: '#00ffcc',
    backgroundColor: '#001a14',
  },
  metricLabel: { color: '#657673', fontSize: 10, fontWeight: 'bold', marginBottom: 3 },
  metricValue: { color: '#f4faf8', fontSize: 13, fontWeight: 'bold', fontFamily: 'monospace' },
  unit: { fontSize: 8, color: '#9aa9a7' },
  hiddenView: { display: 'none' },
  homeTabs: {
    width: '100%',
    maxWidth: 760,
    alignSelf: 'center',
    flexDirection: 'row',
    gap: 4,
    padding: 3,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#1b2926',
    borderRadius: 8,
    backgroundColor: '#0a0d0d',
  },
  homeTab: {
    flex: 1,
    height: 38,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 7,
    borderRadius: 5,
  },
  homeTabActive: { backgroundColor: '#06241d' },
  homeTabText: { color: '#657673', fontSize: 11, fontWeight: '700' },
  homeTabTextActive: { color: '#7ef2d0' },

  diagnosticsCard: {
    width: '100%',
    maxWidth: 760,
    backgroundColor: '#0a0d0d',
    borderRadius: 18,
    borderWidth: 1,
    borderColor: '#1b2926',
    padding: 18,
    marginBottom: 24,
  },
  diagnosticsHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 },
  diagnosticsTitle: { color: '#f4faf8', fontSize: 18, fontWeight: '700', marginTop: 3 },
  refreshButton: { width: 42, height: 42, borderRadius: 12, borderWidth: 1, borderColor: '#1b2926', alignItems: 'center', justifyContent: 'center' },
  diagnosticsEmpty: { color: '#9aa9a7', fontSize: 13, paddingVertical: 24 },
  diagnosticsTabs: { flexDirection: 'row', gap: 4, padding: 3, marginBottom: 12, borderWidth: 1, borderColor: '#1b2926', borderRadius: 8, backgroundColor: '#050707' },
  diagnosticsTab: { flex: 1, minHeight: 36, alignItems: 'center', justifyContent: 'center', borderRadius: 5 },
  diagnosticsTabActive: { backgroundColor: '#06241d' },
  diagnosticsTabText: { color: '#657673', fontSize: 11, fontWeight: '700' },
  diagnosticsTabTextActive: { color: '#7ef2d0' },
  logScroll: { maxHeight: 420, backgroundColor: '#050707', borderRadius: 10, paddingHorizontal: 12 },
  logScrollContent: { paddingTop: 12, paddingBottom: 18 },
  logLine: { color: '#9aa9a7', fontSize: 11, lineHeight: 18, fontFamily: 'monospace', flexShrink: 1, paddingBottom: 2 },
  stateHistoryLoading: { height: 160, alignItems: 'center', justifyContent: 'center' },
  stateHistoryScroll: { maxHeight: 420, borderRadius: 8, backgroundColor: '#050707' },
  stateHistoryTableContent: { minWidth: '100%' },
  stateHistoryTable: { width: '100%', minWidth: 658 },
  stateHistoryRow: { width: '100%', minWidth: 658, flexDirection: 'row', alignItems: 'center', minHeight: 38, borderBottomWidth: 1, borderBottomColor: '#14201d' },
  stateHistoryHeaderRow: { backgroundColor: '#0d1412' },
  stateHistoryHeaderCell: { color: '#657673', fontSize: 9, fontWeight: '800', paddingHorizontal: 8, paddingVertical: 10 },
  stateHistoryCell: { color: '#c4d2ce', fontSize: 10, fontFamily: 'monospace', paddingHorizontal: 8, paddingVertical: 9 },
  stateHistoryTimeCell: { width: 148, flexGrow: 1 },
  stateHistoryModeCell: { width: 76, flexGrow: 1 },
  stateHistoryNumberCell: { width: 62, flexGrow: 1, textAlign: 'center' },
  stateHistoryFluxCell: { width: 112, flexGrow: 1 },
  stateHistoryFlagCell: { width: 66, flexGrow: 1, textAlign: 'center' },
  stateHistoryPagination: { width: '100%', flexDirection: 'row', flexWrap: 'nowrap', alignItems: 'center', justifyContent: 'flex-start', gap: 4, marginTop: 12 },
  stateHistoryPaginationGroup: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  stateHistoryPageButton: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: '#1b2926', borderRadius: 4 },
  stateHistoryPageButtonActive: { backgroundColor: '#06241d', borderColor: '#245e50' },
  stateHistoryPageButtonDisabled: { opacity: 0.5 },
  stateHistoryPageText: { color: '#9aa9a7', fontSize: 10, fontWeight: '700' },
  stateHistoryPageIndicator: { color: '#9aa9a7', fontSize: 10, fontFamily: 'monospace', minWidth: 54, textAlign: 'center' },
  stateRuntimeChart: { paddingVertical: 8 },
  stateRuntimeSummary: { flexDirection: 'row', alignItems: 'baseline', gap: 8 },
  stateRuntimeTotal: { color: '#f4faf8', fontSize: 22, fontWeight: '700', fontFamily: 'monospace' },
  stateRuntimeCaption: { color: '#657673', fontSize: 10, fontWeight: '700' },
  stateRuntimePeriod: { color: '#657673', fontSize: 10, fontFamily: 'monospace', marginTop: 4, marginBottom: 20 },
  stateRuntimeRow: { marginBottom: 16 },
  stateRuntimeLabelRow: { flexDirection: 'row', alignItems: 'center', gap: 7, marginBottom: 6 },
  stateRuntimeSwatch: { width: 8, height: 8, borderRadius: 4 },
  stateRuntimeLabel: { color: '#c4d2ce', fontSize: 11, fontWeight: '700', flex: 1 },
  stateRuntimeValue: { color: '#9aa9a7', fontSize: 10, fontFamily: 'monospace' },
  stateRuntimeTrack: { height: 8, backgroundColor: '#151d1b', borderRadius: 4, overflow: 'hidden' },
  stateRuntimeBar: { height: '100%', borderRadius: 4 },
  stateEnergySummary: { borderTopWidth: 1, borderTopColor: '#1b2926', marginTop: 16, paddingTop: 4 },
  stateEnergyRow: { minHeight: 58, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingVertical: 8 },
  stateEnergyYearlyRow: { borderTopWidth: 1, borderTopColor: '#14201d', borderBottomWidth: 1, borderBottomColor: '#14201d' },
  stateEnergyDetails: { flex: 1, minWidth: 0 },
  stateEnergyLabel: { color: '#c4d2ce', fontSize: 12, fontWeight: '700' },
  stateEnergyCaption: { color: '#657673', fontSize: 10, lineHeight: 14, marginTop: 4 },
  stateEnergyValue: { color: '#7ef2d0', fontSize: 17, fontWeight: '700', fontFamily: 'monospace' },
  statePowerBreakdown: { marginTop: 16 },
  statePowerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: '#14201d' },
  statePowerLabel: { color: '#9aa9a7', fontSize: 11 },
  statePowerValue: { color: '#c4d2ce', fontSize: 11, fontFamily: 'monospace' },
  diagnosticsFootnote: { color: '#657673', fontSize: 10, fontFamily: 'monospace', marginTop: 10 },

  // --- HISTORY CHARTS ---
  historyModalScreen: {
    flex: 1,
    backgroundColor: '#000000',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 20,
  },
  historyModalCard: {
    width: '90%',
    flex: 1,
    backgroundColor: '#000000',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: '#222222',
  },
  historyChartCard: {
    width: '100%',
    flex: 1,
    backgroundColor: '#0a0d0d',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#1b2926',
    padding: 14,
  },
  historyChooserLabel: { color: '#657673', fontSize: 10, fontWeight: '800', letterSpacing: 1.2, marginBottom: 7 },
  historyMetricChooserScroll: { flexGrow: 0, marginBottom: 12 },
  historyMetricChooser: { gap: 7, paddingRight: 8 },
  historyMetricChoice: {
    borderWidth: 1,
    borderColor: '#1b2926',
    borderRadius: 8,
    paddingHorizontal: 11,
    paddingVertical: 8,
  },
  historyMetricChoiceActive: { backgroundColor: '#06241d', borderColor: '#00d9ae' },
  historyMetricChoiceText: { color: '#9aa9a7', fontSize: 10, fontWeight: '800' },
  historyMetricChoiceTextActive: { color: '#7ef2d0' },
  historyChartHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 8,
  },
  historyChartLabel: { color: '#657673', fontSize: 10, fontWeight: '800', letterSpacing: 0.8, marginBottom: 5 },
  historyChartValue: { fontSize: 22, fontWeight: 'bold', fontFamily: 'monospace' },
  historyChartMeta: { alignItems: 'flex-end' },
  historyChartRange: { color: '#657673', fontSize: 9, fontWeight: '800', letterSpacing: 0.8 },
  historyChartRangeValue: { color: '#9aa9a7', fontSize: 11, fontFamily: 'monospace', marginTop: 3 },
  historySelectedTime: { color: '#7ef2d0', fontSize: 10, fontFamily: 'monospace', marginTop: 6 },
  chartPlot: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 1,
    borderBottomWidth: 1,
    borderBottomColor: '#1b2926',
    minHeight: 220,
    position: 'relative',
    overflow: 'hidden',
  },
  chartGridLineTop: { position: 'absolute', top: '25%', left: 0, right: 0, borderTopWidth: 1, borderTopColor: '#12201d' },
  chartGridLineMiddle: { position: 'absolute', top: '50%', left: 0, right: 0, borderTopWidth: 1, borderTopColor: '#12201d' },
  chartBar: {
    flex: 1,
    minWidth: 3,
    borderWidth: 1,
    borderTopLeftRadius: 2,
    borderTopRightRadius: 2,
  },
  emptyHistoryText: {
    color: '#333333',
    fontSize: 10,
    fontWeight: 'bold',
    textAlign: 'center',
    width: '100%',
    marginBottom: 28,
  },
  historyTimeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 5,
  },
  historyTimeText: { color: '#444444', fontSize: 8, fontFamily: 'monospace' },
  historyNavigator: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginTop: 12,
  },
  historyNavButton: {
    width: 52,
    height: 52,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#1b2926',
  },
  historyNavButtonDisabled: {
    opacity: 0.55,
  },
  historyScrollbar: {
    flex: 1,
    height: 48,
  },
  historyScrollbarContent: {
    alignItems: 'center',
    gap: 3,
    paddingHorizontal: 2,
  },
  historyScrollbarSegment: {
    width: 18,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#222222',
  },
  historyScrollbarSegmentActive: {
    width: 28,
    backgroundColor: '#00ffcc',
  },
  historyCloseButton: {
    width: 28,
    height: 28,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#222222',
  },
  historyFootnote: {
    color: '#6c757d',
    fontSize: 9,
    fontFamily: 'monospace',
    marginTop: 8,
    textAlign: 'center',
  },
  menuOverlay: { flex: 1, flexDirection: 'row' },
  menuBackdrop: { flex: 1, backgroundColor: 'rgba(0, 0, 0, 0.72)' },
  menuPanel: { width: '84%', maxWidth: 360, backgroundColor: '#0a0d0d', borderRightWidth: 1, borderRightColor: '#1b2926', padding: 22, paddingTop: 58 },
  menuPanelHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 28 },
  menuTitle: { color: '#f4faf8', fontSize: 24, fontWeight: '700', marginTop: 4 },
  menuItem: { flexDirection: 'row', alignItems: 'center', borderRadius: 12, padding: 13, marginBottom: 8 },
  menuItemActive: { backgroundColor: '#06241d' },
  menuItemCopy: { flex: 1, marginLeft: 13 },
  menuItemLabel: { color: '#f4faf8', fontSize: 15, fontWeight: '700' },
  menuItemLabelActive: { color: '#7ef2d0' },
  menuItemDetail: { color: '#657673', fontSize: 11, marginTop: 3 },
  menuActiveDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#7ef2d0' },

  // --- ZIGBEE STYLES ---
  zigbeeContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    width: '100%',
    maxWidth: 760,
    marginBottom: 20,
  },
  zigbeeCard: {
    width: '49%',
    backgroundColor: '#000000',
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: '#222222',
    alignItems: 'center',
  },
  zigbeeCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    width: '100%',
    borderBottomWidth: 1,
    borderBottomColor: '#222222',
    paddingBottom: 6,
  },
  zigbeeCardTitle: {
    color: '#8e9aaf',
    fontSize: 10,
    fontWeight: 'bold',
    letterSpacing: 1,
  },
  zigbeeBatteryText: {
    color: '#8e9aaf',
    fontSize: 10,
    fontFamily: 'monospace',
  },
  zigbeeMetricsRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    width: '100%',
    marginTop: 8,
  },
  zigbeeMetric: {
    alignItems: 'center',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: 'transparent',
    paddingVertical: 4,
    paddingHorizontal: 8,
  },

  // --- LCD STYLES ---
  lcdScreen: {
    width: '100%',
    maxWidth: 760,
    backgroundColor: '#0a0d0d',
    borderColor: '#1b2926',
    borderWidth: 1.5,
    borderRadius: 16,
    padding: 16,
    marginBottom: 24,
  },
  lcdHeaderTitle: {
    color: '#7ef2d0',
    fontSize: 10,
    fontWeight: 'bold',
    letterSpacing: 1,
    textAlign: 'center',
    marginBottom: 10,
    opacity: 0.8,
  },
  controlNotice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    backgroundColor: '#101615',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 8,
  },
  controlNoticeText: { flex: 1, color: '#9aa9a7', fontSize: 11, lineHeight: 16 },
  currentStatusCard: {
    width: '100%',
    maxWidth: 760,
    backgroundColor: '#101615',
    borderColor: '#1b2926',
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  currentStatusHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    marginBottom: 12,
  },
  currentStatusTitle: { color: '#f4faf8', fontSize: 14, fontWeight: '700', marginTop: 4 },
  automationBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderRadius: 14,
    paddingHorizontal: 9,
    paddingVertical: 6,
  },
  automationBadgeOn: { backgroundColor: '#06241d' },
  automationBadgeOff: { backgroundColor: '#18201f' },
  automationDot: { width: 7, height: 7, borderRadius: 4 },
  automationBadgeText: { color: '#9aa9a7', fontSize: 10, fontWeight: '800', letterSpacing: 0.5 },
  currentStatusGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  currentStatusItem: {
    flexGrow: 1,
    flexBasis: '22%',
    minWidth: 112,
    backgroundColor: '#0a0d0d',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 9,
  },
  currentStatusLabel: { color: '#657673', fontSize: 9, fontWeight: '800', letterSpacing: 0.8 },
  currentStatusValue: { color: '#7ef2d0', fontSize: 12, fontWeight: '700', marginTop: 4 },
  lcdRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'stretch', marginVertical: 4, gap: 8 },
  indicatorBlock: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  statusBox: {
    flex: 1,
    backgroundColor: '#0a0d0d',
    borderColor: '#1b2926',
    borderWidth: 1,
    borderRadius: 8,
    minHeight: 102,
    paddingVertical: 8,
    paddingHorizontal: 8,
    marginHorizontal: 3,
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 0,
  },
  statusBoxHighlighted: { borderColor: '#00d9ae', backgroundColor: '#06241d' },
  statusBoxAutoHighlighted: { borderColor: '#245e50', backgroundColor: '#071512' },
  statusBoxDisabledBorder: { borderColor: '#1b2926', backgroundColor: '#0a0d0d' },
  statusBoxDisabled: { opacity: 0.4 },
  phantomLevelIcons: { flexDirection: 'row', alignItems: 'flex-end', minHeight: 24, gap: 2 },
  statusBoxLabel: { color: '#00ffcc', fontSize: 10, fontWeight: 'bold', opacity: 0.8 },
  statusBoxLabelDisabled: { color: '#444' },
  controlLabel: { color: '#9aa9a7', fontSize: 10, fontWeight: '800', letterSpacing: 0.5, marginTop: 8 },
  controlLabelDisabled: { color: '#657673' },
  statusBoxValue: { color: '#00ffcc', fontSize: 11, fontWeight: 'bold', fontFamily: 'monospace' },
  lcdText: { color: '#00ffcc', fontSize: 13, fontWeight: 'bold', fontFamily: 'monospace' },
  disabledText: { color: '#333333' },
  disabledTextLabel: { color: '#333333', opacity: 1 },
  
  // --- BUTTON GRID ---
  grid: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', width: '90%' },
  button: {
    width: '48%',
    height: 52,
    marginBottom: 6,
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
    flexDirection: 'row',
    gap: 8,
    borderWidth: 1,
    borderColor: '#222222',
  },
  disabledButton: { opacity: 0.2 },
  btnText: { color: '#fff', fontSize: 14, fontWeight: '700' },
});