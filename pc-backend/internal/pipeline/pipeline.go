// Package pipeline — plugin chain processor for DataFrame objects.
package pipeline

import (
	"telemetry/internal/channels"
	"telemetry/internal/pipeline/plugins"
	"telemetry/internal/ring"
)

// Pipeline applies a chain of plugins to each DataFrame.
type Pipeline struct {
	chain []plugins.Plugin
}

// New creates a Pipeline with the given plugins in order.
func New(pluginList []plugins.Plugin) *Pipeline {
	return &Pipeline{chain: pluginList}
}

// Process runs all enabled plugins on f in sequence.
// If a plugin returns nil, the frame is dropped.
func (p *Pipeline) Process(f ring.DataFrame, cm channels.ChannelMap) *ring.DataFrame {
	out := &f
	for _, pl := range p.chain {
		out = pl.Process(out, cm)
		if out == nil {
			return nil // plugin dropped the frame
		}
	}
	return out
}
