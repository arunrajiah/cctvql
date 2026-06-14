/**
 * PTZJoystick
 * ───────────
 * D-pad style control for pan/tilt/zoom.
 * Uses onPressIn / onPressOut to hold-to-move, firing stop on release.
 */
import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { ActivityIndicator, StyleSheet, TouchableOpacity, View } from 'react-native';
import { sendPTZCommand } from '../api/cameras';

type Action = Parameters<typeof sendPTZCommand>[1];

interface Props {
  onCommand: (action: Action, opts?: { speed?: number }) => Promise<void>;
  loading: boolean;
}

const SPEED = 50;

export default function PTZJoystick({ onCommand, loading }: Props) {
  return (
    <View style={styles.root}>
      {loading && <ActivityIndicator style={StyleSheet.absoluteFillObject} color="#3b82f6" />}

      {/* D-pad */}
      <View style={styles.dpad}>
        {/* Up */}
        <View style={styles.row}>
          <PTZBtn icon="chevron-up" action="up" onCommand={onCommand} />
        </View>
        {/* Left / Stop / Right */}
        <View style={styles.row}>
          <PTZBtn icon="chevron-back" action="left" onCommand={onCommand} />
          <PTZBtn icon="stop-circle-outline" action="stop" onCommand={onCommand} />
          <PTZBtn icon="chevron-forward" action="right" onCommand={onCommand} />
        </View>
        {/* Down */}
        <View style={styles.row}>
          <PTZBtn icon="chevron-down" action="down" onCommand={onCommand} />
        </View>
      </View>

      {/* Zoom */}
      <View style={styles.zoom}>
        <PTZBtn icon="add-circle-outline" action="zoom_in" onCommand={onCommand} />
        <PTZBtn icon="remove-circle-outline" action="zoom_out" onCommand={onCommand} />
      </View>
    </View>
  );
}

function PTZBtn({
  icon,
  action,
  onCommand,
}: {
  icon: React.ComponentProps<typeof Ionicons>['name'];
  action: Action;
  onCommand: Props['onCommand'];
}) {
  let holdInterval: ReturnType<typeof setInterval> | null = null;

  const startHold = () => {
    onCommand(action, { speed: SPEED });
    holdInterval = setInterval(() => onCommand(action, { speed: SPEED }), 200);
  };

  const endHold = () => {
    if (holdInterval) clearInterval(holdInterval);
    holdInterval = null;
    if (action !== 'stop') onCommand('stop');
  };

  return (
    <TouchableOpacity
      style={styles.btn}
      onPressIn={startHold}
      onPressOut={endHold}
      delayPressIn={0}
    >
      <Ionicons name={icon} size={22} color="#f8fafc" />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  root: { alignItems: 'center', gap: 16 },
  dpad: { gap: 4 },
  row: { flexDirection: 'row', gap: 4, justifyContent: 'center' },
  zoom: { flexDirection: 'row', gap: 16 },
  btn: {
    width: 52,
    height: 52,
    borderRadius: 12,
    backgroundColor: '#0f172a',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#334155',
  },
});
