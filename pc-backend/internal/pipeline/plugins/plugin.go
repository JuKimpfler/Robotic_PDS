// Package plugins — Plugin interface and built-in plugin implementations.
package plugins

import (
	"telemetry/internal/channels"
	"telemetry/internal/ring"
)

// Plugin is the interface all data processing plugins must implement.
type Plugin interface {
	// Name returns the unique plugin identifier.
	Name() string
	// Process transforms a DataFrame. Returns nil to drop the frame.
	// Must never block. Must not modify the input frame's Values slice in-place
	// if the slice may be shared; copy before modifying.
	Process(f *ring.DataFrame, ch channels.ChannelMap) *ring.DataFrame
}
