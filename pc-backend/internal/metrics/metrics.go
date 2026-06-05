// Package metrics — Prometheus counters and gauges per §13 of the spec.
package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	// FramesReceived counts fully reassembled UDP frames.
	FramesReceived = promauto.NewCounter(prometheus.CounterOpts{
		Name: "telemetry_frames_received_total",
		Help: "UDP frames fully reassembled.",
	})

	// FramesDropped counts frames dropped due to full ring buffer or reassembly timeout.
	FramesDropped = promauto.NewCounter(prometheus.CounterOpts{
		Name: "telemetry_frames_dropped_total",
		Help: "Frames dropped (ring full / reassembly timeout).",
	})

	// CRCErrors counts CRC validation failures on received UDP sub-packets.
	CRCErrors = promauto.NewCounter(prometheus.CounterOpts{
		Name: "telemetry_crc_errors_total",
		Help: "CRC validation failures.",
	})

	// UDPBytesTotal counts raw UDP bytes received on port 9000.
	UDPBytesTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "telemetry_udp_bytes_total",
		Help: "Raw UDP bytes received.",
	})

	// FrameRateHz is the measured incoming frame rate (server-side).
	FrameRateHz = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "telemetry_frame_rate_hz",
		Help: "Measured incoming frame rate (Hz).",
	})

	// WSClients is the current number of active WebSocket clients.
	WSClients = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "telemetry_ws_clients",
		Help: "Active WebSocket clients.",
	})

	// WSFramesDropped counts frames dropped due to slow WebSocket clients.
	WSFramesDropped = promauto.NewCounter(prometheus.CounterOpts{
		Name: "telemetry_ws_frames_dropped_total",
		Help: "Frames dropped due to slow WS clients.",
	})

	// ReassemblyTimeouts counts sub-packet reassembly timeouts.
	ReassemblyTimeouts = promauto.NewCounter(prometheus.CounterOpts{
		Name: "telemetry_reassembly_timeouts_total",
		Help: "Sub-packet reassembly timeouts.",
	})

	// HotspotState is 1 when the hotspot is on, 0 when off.
	HotspotState = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "telemetry_hotspot_state",
		Help: "Hotspot state: 1=on, 0=off.",
	})
)
