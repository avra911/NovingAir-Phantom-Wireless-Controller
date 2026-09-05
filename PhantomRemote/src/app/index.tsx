import React, { useState, useEffect } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  ScrollView
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MaterialCommunityIcons, Ionicons } from '@expo/vector-icons';

const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

export interface PhantomState {
  mode: 'AUTO' | 'SLEEP' | 'MANUAL';
  speed: number;
  humidity: number;
  flux: 'SOUTH_NORTH' | 'EXTRACT' | 'INTAKE' | 'NORTH_SOUTH';
  night: boolean;
  boost: boolean;
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

export interface CombinedState {
  phantom: PhantomState;
  sensor: SensorMetrics;
}

const DEFAULT_PHANTOM: PhantomState = {
  mode: 'AUTO',
  speed: 3,
  humidity: 3,
  flux: 'SOUTH_NORTH',
  night: false,
  boost: false,
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

export default function Index() {
  const [phantomState, setPhantomState] = useState<PhantomState>(DEFAULT_PHANTOM);
  const [sensorMetrics, setSensorMetrics] = useState<SensorMetrics>(DEFAULT_SENSOR);
  const [loading, setLoading] = useState<string | null>(null);
  const [initialFetching, setInitialFetching] = useState<boolean>(true);

  useEffect(() => {
    fetchState();

    // Auto-refresh sensor readings every 10 seconds
    const interval = setInterval(fetchState, 10000);

    return () => clearInterval(interval);
  }, []);

  const fetchState = async () => {
    try {
      const res = await fetch(`${API_URL}/state`);

      if (res.ok) {
        const data: CombinedState = await res.json();
        setPhantomState(data.phantom);
        setSensorMetrics(data.sensor);
      }
    } catch (err) {
      console.error("Failed to sync initial state:", err);
    } finally {
      setInitialFetching(false);
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
    } catch (err) {
      console.error(`Error executing action ${actionKey}:`, err);

      Alert.alert(
        "API Error",
        "Unable to communicate with Phantom Controller backend."
      );
    } finally {
      setLoading(null);
    }
  };

  const buttons = [
    {
      label: "BOOST",
      key: "BOOST",
      color: "#e74c3c",
      icon: "rocket-outline"
    },
    {
      label: "NIGHT",
      key: "NIGHT",
      color: "#34495e",
      icon: "moon-outline"
    },
    {
      label: "SPEED",
      key: "SPEED",
      color: "#2980b9",
      icon: "speedometer-outline"
    },
    {
      label: "MODE",
      key: "MODE",
      color: "#27ae60",
      icon: "options-outline"
    },
    {
      label: "FLUX",
      key: "FLUX",
      color: "#8e44ad",
      icon: "swap-horizontal-outline"
    },
    {
      label: "HUMIDITY",
      key: "HUMIDITY",
      color: "#d35400",
      icon: "water-outline"
    },
    {
      label: "RESET",
      key: "RESET",
      color: "#7f8c8d",
      icon: "refresh-outline"
    },
  ];

  const getFluxIcon = (flux: PhantomState['flux']) => {
    switch (flux) {
      case 'SOUTH_NORTH':
        return "sync";
      case 'EXTRACT':
        return "sync-off";
      case 'INTAKE':
        return "arrow-down-bold";
      case 'NORTH_SOUTH':
        return "arrow-up-bold";
      default:
        return "sync";
    }
  };

  /*
    HEALTH THRESHOLDS FOR AIR QUALITY METRICS

    Metric      | Good          | Moderate      | Unhealthy
    ============|===============|===============|===============
    CO2         | <800 ppm      | 800-1200      | >1200
    Temp        | 18-24°C       | 15-28°C       | <15 or >28
    Humidity    | 30-50%        | 25-60%        | <25 or >60%
    PM1.0       | <12 µg/m³     | 12-35         | 35-55 | >55
    PM2.5       | <12 µg/m³     | 12-35         | 35-55 | >55
    PM10        | <12 µg/m³     | 12-35         | 35-55 | >55
    TVOC        | <0.3 mg/m³    | 0.3-1.0       | >1.0
    HCHO        | <0.05 mg/m³   | 0.05-0.1      | >0.1

    Color coding:
    Cyan (#00ffcc) = Good/Healthy
    Orange (#f39c12) = Moderate/Caution
    Red (#e74c3c) = Unhealthy/Poor
  */

  // Health-based color coding functions
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

  if (initialFetching) {
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
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        <Text style={styles.title}>NovingAir Control Hub</Text>

        {/* --- 8-IN-1 AIR QUALITY MONITOR PANEL --- */}
        <View style={styles.sensorCard}>
          <View style={styles.cardHeader}>
            <View style={styles.indicatorBlock}>
              <MaterialCommunityIcons
                name="molecule-co2"
                size={24}
                color={getCO2Color(sensorMetrics.co2_ppm)}
              />

              <Text style={styles.cardHeaderTitle}>
                AIR QUALITY
              </Text>
            </View>

            <View style={styles.indicatorBlock}>
              <MaterialCommunityIcons
                name={
                  sensorMetrics.battery_pct > 20
                    ? "battery-high"
                    : "battery-low"
                }
                size={18}
                color={sensorMetrics.online ? "#00ffcc" : "#e74c3c"}
              />

              <Text style={styles.statusText}>
                {sensorMetrics.online
                  ? `${sensorMetrics.battery_pct}%`
                  : 'OFFLINE'}
              </Text>
            </View>
          </View>

          {/* Metric Grid - 8 Indicators */}
          <View style={styles.metricsGrid}>
            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>CO2</Text>
              <Text
                style={[
                  styles.metricValue,
                  { color: getCO2Color(sensorMetrics.co2_ppm) }
                ]}
              >
                {sensorMetrics.co2_ppm}
                <Text style={styles.unit}> ppm</Text>
              </Text>
            </View>

            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>TEMP</Text>
              <Text
                style={[
                  styles.metricValue,
                  { color: getTempColor(sensorMetrics.temperature_c) }
                ]}
              >
                {sensorMetrics.temperature_c}
                <Text style={styles.unit}> °C</Text>
              </Text>
            </View>

            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>HUMIDITY</Text>
              <Text
                style={[
                  styles.metricValue,
                  { color: getHumidityColor(sensorMetrics.humidity_pct) }
                ]}
              >
                {sensorMetrics.humidity_pct}
                <Text style={styles.unit}> %</Text>
              </Text>
            </View>

            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>PM1.0</Text>
              <Text
                style={[
                  styles.metricValue,
                  { color: getPMColor(sensorMetrics.pm1_ugm3) }
                ]}
              >
                {sensorMetrics.pm1_ugm3}
                <Text style={styles.unit}> µg/m³</Text>
              </Text>
            </View>

            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>PM2.5</Text>
              <Text
                style={[
                  styles.metricValue,
                  { color: getPMColor(sensorMetrics.pm25_ugm3) }
                ]}
              >
                {sensorMetrics.pm25_ugm3}
                <Text style={styles.unit}> µg/m³</Text>
              </Text>
            </View>

            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>PM10</Text>
              <Text
                style={[
                  styles.metricValue,
                  { color: getPMColor(sensorMetrics.pm10_ugm3) }
                ]}
              >
                {sensorMetrics.pm10_ugm3}
                <Text style={styles.unit}> µg/m³</Text>
              </Text>
            </View>

            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>TVOC</Text>
              <Text
                style={[
                  styles.metricValue,
                  { color: getTVOCColor(sensorMetrics.voc_mgm3) }
                ]}
              >
                {sensorMetrics.voc_mgm3}
                <Text style={styles.unit}> mg/m³</Text>
              </Text>
            </View>

            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>HCHO</Text>
              <Text
                style={[
                  styles.metricValue,
                  { color: getFormaldehyteColor(sensorMetrics.ch2o_mgm3) }
                ]}
              >
                {sensorMetrics.ch2o_mgm3}
                <Text style={styles.unit}> mg/m³</Text>
              </Text>
            </View>
          </View>
        </View>

        {/* --- HRV LCD STATUS SCREEN --- */}
        <View style={styles.lcdScreen}>
          <Text style={styles.lcdHeaderTitle}>
            PHANTOM UNIT STATUS
          </Text>

          <View style={styles.lcdRow}>
            {/* Operating mode */}
            <View style={styles.indicatorBlock}>
              <MaterialCommunityIcons
                name={
                  phantomState.mode === 'AUTO'
                    ? "brightness-auto"
                    : phantomState.mode === 'SLEEP'
                      ? "sleep"
                      : "gesture-tap"
                }
                size={22}
                color="#00ffcc"
              />

              <Text style={styles.lcdText}>
                {phantomState.mode}
              </Text>
            </View>

            {/* Fan speed */}
            <View style={styles.indicatorBlock}>
              <MaterialCommunityIcons
                name="fan"
                size={22}
                color={
                  phantomState.mode === 'MANUAL'
                    ? "#00ffcc"
                    : "#112a2a"
                }
              />

              <Text
                style={[
                  styles.lcdText,
                  phantomState.mode !== 'MANUAL' &&
                    styles.disabledText
                ]}
              >
                SPD: {phantomState.speed}
              </Text>
            </View>

            {/* Humidity level */}
            <View style={styles.indicatorBlock}>
              <MaterialCommunityIcons
                name="water-percent"
                size={22}
                color={
                  phantomState.mode !== 'MANUAL'
                    ? "#00ffcc"
                    : "#112a2a"
                }
              />

              <Text
                style={[
                  styles.lcdText,
                  phantomState.mode === 'MANUAL' &&
                    styles.disabledText
                ]}
              >
                HUM: {phantomState.humidity}
              </Text>
            </View>
          </View>

          <View style={styles.lcdRow}>
            {/* Airflow direction */}
            <View style={styles.indicatorBlock}>
              <MaterialCommunityIcons
                name={getFluxIcon(phantomState.flux)}
                size={20}
                color="#00ffcc"
              />

              <Text style={styles.lcdText}>
                {phantomState.flux === 'EXTRACT'
                  ? 'EXTRACT'
                  : phantomState.flux}
              </Text>
            </View>

            {/* Night mode indicator */}
            <MaterialCommunityIcons
              name="weather-night"
              size={22}
              color={
                phantomState.night
                  ? "#00ffcc"
                  : "#112a2a"
              }
            />

            {/* Boost indicator */}
            <MaterialCommunityIcons
              name="lightning-bolt"
              size={22}
              color={
                phantomState.boost
                  ? "#00ffcc"
                  : "#112a2a"
              }
            />
          </View>
        </View>

        {/* --- REMOTE CONTROL BUTTONS --- */}
        <View style={styles.grid}>
          {buttons.map((btn) => {
            const isDisabled = loading !== null;

            return (
              <TouchableOpacity
                key={btn.key}
                style={[
                  styles.button,
                  { backgroundColor: btn.color },
                  isDisabled && styles.disabledButton
                ]}
                onPress={() => sendCommand(btn.key)}
                disabled={isDisabled}
              >
                {loading === btn.key ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons
                      name={btn.icon as any}
                      size={20}
                      color="#fff"
                    />

                    <Text style={styles.btnText}>
                      {btn.label}
                    </Text>
                  </>
                )}
              </TouchableOpacity>
            );
          })}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#121212'
  },

  scrollContent: {
    alignItems: 'center',
    paddingVertical: 20
  },

  title: {
    fontSize: 22,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 16
  },

  /* Sensor Card Styles */
  sensorCard: {
    width: '90%',
    backgroundColor: '#1a1d21',
    borderRadius: 16,
    padding: 16,
    marginBottom: 20,
    borderWidth: 1,
    borderColor: '#2d3238',
  },

  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#2d3238',
    paddingBottom: 8,
  },

  cardHeaderTitle: {
    color: '#8e9aaf',
    fontSize: 12,
    fontWeight: 'bold',
    letterSpacing: 1
  },

  statusText: {
    color: '#8e9aaf',
    fontSize: 11,
    fontFamily: 'monospace'
  },

  metricsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
  },

  metricItem: {
    width: '23%',
    backgroundColor: '#121417',
    borderRadius: 8,
    padding: 8,
    marginBottom: 8,
    alignItems: 'center',
  },

  metricLabel: {
    color: '#6c757d',
    fontSize: 9,
    fontWeight: 'bold',
    marginBottom: 2
  },

  metricValue: {
    color: '#fff',
    fontSize: 12,
    fontWeight: 'bold',
    fontFamily: 'monospace'
  },

  unit: {
    fontSize: 8,
    color: '#6c757d'
  },

  /* LCD Screen Styles */
  lcdScreen: {
    width: '90%',
    backgroundColor: '#071515',
    borderColor: '#00ffcc',
    borderWidth: 2,
    borderRadius: 16,
    padding: 16,
    marginBottom: 24,
    elevation: 8,
  },

  lcdHeaderTitle: {
    color: '#00ffcc',
    fontSize: 10,
    fontWeight: 'bold',
    letterSpacing: 1,
    textAlign: 'center',
    marginBottom: 10,
    opacity: 0.6,
  },

  lcdRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    alignItems: 'center',
    marginVertical: 6,
  },

  indicatorBlock: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4
  },

  lcdText: {
    color: '#00ffcc',
    fontSize: 13,
    fontWeight: 'bold',
    fontFamily: 'monospace'
  },

  disabledText: {
    color: '#112a2a'
  },

  /* Control Grid Styles */
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    width: '90%'
  },

  button: {
    width: '42%',
    height: 56,
    margin: 6,
    borderRadius: 14,
    justifyContent: 'center',
    alignItems: 'center',
    flexDirection: 'row',
    gap: 8,
    elevation: 4,
  },

  disabledButton: {
    opacity: 0.25,
  },

  btnText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '700'
  },
});