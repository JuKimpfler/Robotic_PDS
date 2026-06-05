// moving_average.go — sliding window moving average per channel.
package plugins

import (
	"telemetry/internal/channels"
	"telemetry/internal/ring"
)

// MovingAverage applies a simple N-sample sliding window to each channel.
type MovingAverage struct {
	window int
	bufs   [][]float32 // circular buffer per channel
	pos    []int
	full   []bool
}

// NewMovingAverage creates a MovingAverage plugin with the given window size.
func NewMovingAverage(window int) *MovingAverage {
	if window < 1 {
		window = 1
	}
	return &MovingAverage{window: window}
}

func (*MovingAverage) Name() string { return "moving_average" }

func (ma *MovingAverage) Process(f *ring.DataFrame, _ channels.ChannelMap) *ring.DataFrame {
	n := len(f.Values)
	if n == 0 {
		return f
	}

	// Lazy init when first frame arrives (channel count may vary)
	if len(ma.bufs) != n {
		ma.bufs = make([][]float32, n)
		ma.pos = make([]int, n)
		ma.full = make([]bool, n)
		for i := range ma.bufs {
			ma.bufs[i] = make([]float32, ma.window)
		}
	}

	out := make([]float32, n)
	for i, v := range f.Values {
		buf := ma.bufs[i]
		buf[ma.pos[i]] = v
		ma.pos[i] = (ma.pos[i] + 1) % ma.window
		if ma.pos[i] == 0 {
			ma.full[i] = true
		}

		count := ma.window
		if !ma.full[i] {
			count = ma.pos[i]
			if count == 0 {
				count = 1
			}
		}
		var sum float32
		for _, x := range buf[:count] {
			sum += x
		}
		out[i] = sum / float32(count)
	}

	result := *f
	result.Values = out
	return &result
}
