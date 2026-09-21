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
import { MaterialCommunityIcons, Ionicons } from '@expo/vector-icons';
import { useFonts } from 'expo-font';

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

const HISTORY_CHARTS: HistoryChartConfig[] = [
  { key: 'co2_ppm', label: 'CO2', unit: 'ppm', color: '#00ffcc' },
  { key: 'temperature_c', label: 'AIR TEMP', unit: '°C', color: '#f39c12', precision: 1 },
  { key: 'humidity_pct', label: 'AIR HUM', unit: '%', color: '#3498db' },
  { key: 'pm1_ugm3', label: 'PM1.0', unit: 'µg/m³', color: '#7bed9f', precision: 1 },
  { key: 'pm25_ugm3', label: 'PM2.5', unit: 'µg/m³', color: '#a8e6cf', precision: 1 },
  { key: 'pm10_ugm3', label: 'PM10', unit: 'µg/m³', color: '#f1c40f', precision: 1 },
  { key: 'voc_mgm3', label: 'TVOC', unit: 'mg/m³', color: '#e67e22', precision: 2 },
  { key: 'ch2o_mgm3', label: 'HCHO', unit: 'mg/m³', color: '#e74c3c', precision: 2 },
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
          <Text style={styles.historyChartLabel}>{config.label}</Text>
          <Text style={[styles.historyChartValue, { color: displayColor }]}> 
            {formatMetricNumber(displayValue, config.precision)}<Text style={styles.unit}> {config.unit}</Text>
          </Text>
        </View>
        <View style={styles.historyChartMeta}>
          <Text style={styles.historyChartRange}>
            {formatMetricNumber(minValue, config.precision)}-{formatMetricNumber(maxValue, config.precision)}
          </Text>
          <Text style={styles.historySelectedTime}>
            {formatHistoryTime(selectedSample?.fetched_at ?? visibleSamples[visibleSamples.length - 1]?.fetched_at)}
          </Text>
        </View>
      </View>

      <View style={styles.chartPlot}>
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
              />
            );
          })
        )}
      </View>

      <View style={styles.historyTimeRow}>
        <Text style={styles.historyTimeText}>{formatHistoryTime(visibleSamples[0]?.fetched_at)}</Text>
        <Text style={styles.historyTimeText}>hour {currentWindow + 1}/{totalWindows}</Text>
        <Text style={styles.historyTimeText}>{formatHistoryTime(visibleSamples[visibleSamples.length - 1]?.fetched_at)}</Text>
      </View>

      <View style={styles.historyNavigator}>
        <TouchableOpacity
          style={[styles.historyNavButton, !canPageOlder && styles.historyNavButtonDisabled]}
          disabled={!canPageOlder}
          onPress={showOlderWindow}
        >
          <Ionicons name="chevron-back" size={32} color={canPageOlder ? '#00ffcc' : '#333333'} />
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
          <Ionicons name="chevron-forward" size={32} color={canPageNewer ? '#00ffcc' : '#333333'} />
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
  const [fontsLoaded] = useFonts({ Phantom: require('../../assets/fonts/Phantom.ttf') });

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
      default: return 'master_slave';
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
  const speedControlEnabled = !phantomState.automation_enabled
    && (phantomState.mode === 'MANUAL' || phantomState.flux !== 'NONE');
  const humidityControlEnabled = !phantomState.automation_enabled
    && (phantomState.mode === 'AUTO' || phantomState.mode === 'SLEEP' || phantomState.night);
  const speedStatusActive = phantomState.mode === 'MANUAL' || phantomState.flux !== 'NONE';
  const humidityStatusActive = phantomState.mode === 'AUTO' || phantomState.mode === 'SLEEP';
  const modeClickable = loading === null && !controlsLocked && !phantomState.automation_enabled;
  const speedClickable = loading === null && !controlsLocked && speedControlEnabled;
  const humidityClickable = loading === null && !controlsLocked && humidityControlEnabled;
  const fluxClickable = loading === null && !controlsLocked && !phantomState.automation_enabled;
  const nightClickable = fluxClickable;
  const boostClickable = fluxClickable;

  if (!fontsLoaded || initialFetching) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator size="large" color="#00ffcc" />
        <Text style={[styles.lcdText, { marginTop: 16 }]}>
          Connecting to backend...
        </Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <Text style={styles.title}>NovingAir Control Hub</Text>

        {/* --- AIR QUALITY MONITOR PANEL --- */}
        <View style={styles.sensorCard}>
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

          <View style={styles.metricsGrid}>
            <TouchableOpacity
              style={[styles.metricItem, activeHistoryMetric === 'co2_ppm' && styles.metricItemActive]}
              onPress={() => openHistoryMetric('co2_ppm')}
            >
              <Text style={styles.metricLabel}>CO2</Text>
              <Text style={[styles.metricValue, { color: getCO2Color(sensorMetrics.co2_ppm) }]}>
                {sensorMetrics.co2_ppm}<Text style={styles.unit}> ppm</Text>
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.metricItem, activeHistoryMetric === 'temperature_c' && styles.metricItemActive]}
              onPress={() => openHistoryMetric('temperature_c')}
            >
              <Text style={styles.metricLabel}>TEMP</Text>
              <Text style={[styles.metricValue, { color: getTempColor(sensorMetrics.temperature_c) }]}>
                {sensorMetrics.temperature_c}<Text style={styles.unit}> °C</Text>
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.metricItem, activeHistoryMetric === 'humidity_pct' && styles.metricItemActive]}
              onPress={() => openHistoryMetric('humidity_pct')}
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
        <View style={styles.zigbeeContainer}>
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

        {/* --- HRV LCD STATUS SCREEN --- */}
        <View style={styles.lcdScreen}>
          <Text style={styles.lcdHeaderTitle}>PHANTOM UNIT STATUS</Text>

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
              accessibilityLabel="Mode"
            >
              {getModeGlyph(phantomState.mode) ? (
                <PhantomGlyph
                  name={getModeGlyph(phantomState.mode)!}
                  color={modeClickable ? '#00ffcc' : '#444'}
                />
              ) : (
                <MaterialCommunityIcons name="minus-circle-outline" size={18} color="#444" />
              )}
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
              accessibilityLabel="Speed"
            >
              <PhantomLevelGlyphs
                name="fan"
                level={phantomState.speed}
                color={speedClickable ? "#00ffcc" : "#444"}
              />
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
              accessibilityLabel="Humidity target"
            >
              <PhantomLevelGlyphs
                name="humidity"
                level={phantomState.humidity}
                color={humidityClickable ? "#00ffcc" : "#444"}
              />
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
              accessibilityLabel="Air flow"
            >
              {getFluxGlyph(phantomState.flux) ? (
                <PhantomGlyph
                  name={getFluxGlyph(phantomState.flux)!}
                  color={fluxClickable ? '#00ffcc' : '#444'}
                />
              ) : (
                <MaterialCommunityIcons name="minus-circle-outline" size={18} color="#444" />
              )}
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
            >
              <PhantomGlyph name="night" color={nightClickable ? "#00ffcc" : "#444"} />
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
            >
              <PhantomGlyph name="temp_evac" color={boostClickable ? "#00ffcc" : "#444"} />
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
              <MiniHistoryChart config={activeHistoryConfig} samples={historySamples} />
              <Text style={styles.historyFootnote}>{historySamples.length} stored minutes · latest {VISIBLE_CHART_SAMPLES} min shown</Text>
            </View>
          </SafeAreaView>
        )}
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000000' },
  scrollContent: { alignItems: 'center', paddingVertical: 20 },
  title: { fontSize: 22, fontWeight: 'bold', color: '#ffffff', marginBottom: 16 },
  
  sensorCard: {
    width: '90%',
    backgroundColor: '#000000',
    borderRadius: 16,
    padding: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#222222',
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
  cardHeaderTitle: { color: '#8e9aaf', fontSize: 12, fontWeight: 'bold', letterSpacing: 1 },
  statusText: { color: '#8e9aaf', fontSize: 11, fontFamily: 'monospace' },
  metricsGrid: { 
    flexDirection: 'row', 
    flexWrap: 'wrap', 
    justifyContent: 'space-between',
    rowGap: 10,
  },
  metricItem: {
    width: '23%',
    paddingVertical: 4,
    alignItems: 'center',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  metricItemActive: {
    borderColor: '#00ffcc',
    backgroundColor: '#001a14',
  },
  metricLabel: { color: '#6c757d', fontSize: 9, fontWeight: 'bold', marginBottom: 2 },
  metricValue: { color: '#fff', fontSize: 12, fontWeight: 'bold', fontFamily: 'monospace' },
  unit: { fontSize: 8, color: '#6c757d' },

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
    backgroundColor: '#050505',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#1f1f1f',
    padding: 10,
  },
  historyChartHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 8,
  },
  historyChartLabel: { color: '#6c757d', fontSize: 9, fontWeight: 'bold', marginBottom: 2 },
  historyChartValue: { fontSize: 14, fontWeight: 'bold', fontFamily: 'monospace' },
  historyChartMeta: { alignItems: 'flex-end' },
  historyChartRange: { color: '#6c757d', fontSize: 9, fontFamily: 'monospace' },
  historySelectedTime: { color: '#8e9aaf', fontSize: 9, fontFamily: 'monospace', marginTop: 2 },
  chartPlot: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 1,
    borderBottomWidth: 1,
    borderBottomColor: '#222222',
    overflow: 'hidden',
  },
  chartBar: {
    flex: 1,
    minWidth: 1,
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
    width: 58,
    height: 48,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#222222',
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

  // --- ZIGBEE STYLES ---
  zigbeeContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    width: '90%',
    marginBottom: 20,
  },
  zigbeeCard: {
    width: '48%',
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
    width: '90%',
    backgroundColor: '#000000',
    borderColor: 'rgba(0, 255, 204, 0.4)',
    borderWidth: 1.5,
    borderRadius: 16,
    padding: 16,
    marginBottom: 24,
  },
  lcdHeaderTitle: {
    color: '#00ffcc',
    fontSize: 10,
    fontWeight: 'bold',
    letterSpacing: 1,
    textAlign: 'center',
    marginBottom: 10,
    opacity: 0.8,
  },
  lcdRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'stretch', marginVertical: 4, gap: 8 },
  indicatorBlock: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  statusBox: {
    flex: 1,
    backgroundColor: '#000000',
    borderColor: '#1f1f1f',
    borderWidth: 1,
    borderRadius: 8,
    minHeight: 92,
    paddingVertical: 8,
    paddingHorizontal: 8,
    marginHorizontal: 3,
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 0,
  },
  statusBoxHighlighted: { borderColor: '#00ffcc', backgroundColor: '#001a14' },
  statusBoxAutoHighlighted: { borderColor: '#00665a', backgroundColor: '#000a08' },
  statusBoxDisabledBorder: { borderColor: '#1f1f1f', backgroundColor: '#000000' },
  statusBoxDisabled: { opacity: 0.4 },
  phantomLevelIcons: { flexDirection: 'row', alignItems: 'flex-end', minHeight: 24, gap: 2 },
  statusBoxLabel: { color: '#00ffcc', fontSize: 10, fontWeight: 'bold', opacity: 0.8 },
  statusBoxLabelDisabled: { color: '#444' },
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