// calibration.go — applies scale and offset from the channel map.
package plugins

import (
	"telemetry/internal/channels"
	"telemetry/internal/ring"
)

// Calibration applies display = raw * scale + offset for each channel.
// This is the standard way to convert raw sensor readings to display units.
type Calibration struct{}

func (*Calibration) Name() string { return "calibration" }

func (*Calibration) Process(f *ring.DataFrame, cm channels.ChannelMap) *ring.DataFrame {
	if len(f.Values) == 0 {
		return f
	}
	// Copy values to avoid mutating shared slice
	out := make([]float32, len(f.Values))
	for i, v := range f.Values {
		if i < len(cm) {
			out[i] = v*cm[i].Scale + cm[i].Offset
		} else {
			out[i] = v
		}
	}
	result := *f
	result.Values = out
	return &result
}
