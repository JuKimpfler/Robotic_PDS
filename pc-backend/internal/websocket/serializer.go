// Package websocket — MessagePack and JSON serializers for WebSocket frames.
package websocket

import (
	"encoding/json"
	"fmt"
	"math"

	"github.com/vmihailenco/msgpack/v5"
	"telemetry/internal/channels"
	"telemetry/internal/ratecontrol"
	"telemetry/internal/ring"
)

// ── MessagePack binary frame (default, high-frequency) ───────────────────────

// SerializeMsgpack encodes a DataFrame as a MessagePack binary WS frame.
// The values field is packed as a raw []float32 (msgpack bin), not a JSON array.
func SerializeMsgpack(f ring.DataFrame) ([]byte, error) {
	// Use pool buffer to avoid alloc
	buf := encodePool.Get().([]byte)
	defer encodePool.Put(buf[:0]) //nolint:staticcheck

	type wsFrame struct {
		Type   string    `msgpack:"type"`
		Seq    uint16    `msgpack:"seq"`
		TsUs   uint32    `msgpack:"ts_us"`
		RateHz float32   `msgpack:"rate_hz"`
		Values []float32 `msgpack:"values"`
	}

	frame := wsFrame{
		Type:   "frame",
		Seq:    f.Seq,
		TsUs:   f.TsUs,
		RateHz: f.RateHz,
		Values: f.Values,
	}

	b, err := msgpack.Marshal(frame)
	if err != nil {
		return nil, fmt.Errorf("msgpack marshal: %w", err)
	}
	return b, nil
}

// ── JSON frame (debug / fallback) ─────────────────────────────────────────────

// SerializeJSON encodes a DataFrame as JSON for debug/fallback clients.
func SerializeJSON(f ring.DataFrame) ([]byte, error) {
	type wsFrame struct {
		Type   string    `json:"type"`
		Seq    uint16    `json:"seq"`
		TsUs   uint32    `json:"ts_us"`
		RateHz float32   `json:"rate_hz"`
		Values []float32 `json:"values"`
	}
	return json.Marshal(wsFrame{
		Type:   "frame",
		Seq:    f.Seq,
		TsUs:   f.TsUs,
		RateHz: f.RateHz,
		Values: f.Values,
	})
}

// ── Channel map push ─────────────────────────────────────────────────────────

// SerializeChannelMap encodes the channel map as a JSON "channel_map" message.
func SerializeChannelMap(cm channels.ChannelMap) ([]byte, error) {
	type msg struct {
		Type     string              `json:"type"`
		Channels channels.ChannelMap `json:"channels"`
	}
	return json.Marshal(msg{Type: "channel_map", Channels: cm})
}

// SerializeParamMap encodes parameter definitions as a JSON "param_map" message.
func SerializeParamMap(params []ratecontrol.ParamDef) ([]byte, error) {
	type msg struct {
		Type   string                 `json:"type"`
		Params []ratecontrol.ParamDef `json:"params"`
	}
	return json.Marshal(msg{Type: "param_map", Params: params})
}

// ── Status push (1 Hz) ───────────────────────────────────────────────────────

// StatusMsg is the "status" message sent to all WS clients at 1 Hz.
type StatusMsg struct {
	Type          string  `json:"type"`
	Hotspot       string  `json:"hotspot"`
	RpiIP         string  `json:"rpi_ip"`
	FramesRx      uint64  `json:"frames_rx"`
	FramesDropped uint64  `json:"frames_dropped"`
	CRCErrors     uint64  `json:"crc_errors"`
	RateHz        float64 `json:"rate_hz"`
}

// SerializeStatus encodes a StatusMsg as JSON.
func SerializeStatus(s StatusMsg) ([]byte, error) {
	s.Type = "status"
	return json.Marshal(s)
}

// ── Helpers ───────────────────────────────────────────────────────────────────

// float32bits returns the IEEE 754 bit pattern of a float32.
// Used for exact dummy-value comparison.
func float32bits(f float32) uint32 {
	return math.Float32bits(f)
}
