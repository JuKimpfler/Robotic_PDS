// Package ring provides a lock-free single-producer / single-consumer ring buffer.
package ring

import (
	"sync/atomic"
)

// RingSize must be a power of 2.
const RingSize = 1024

// DataFrame is one fully-assembled telemetry frame.
type DataFrame struct {
	Seq    uint16
	TsUs   uint32
	Values []float32 // len == channel_count from the frame
	RateHz float32
}

// Buffer is a lock-free ring buffer for DataFrame objects.
// One goroutine writes (Push), one reads (Pop).
type Buffer struct {
	slots [RingSize]DataFrame
	head  atomic.Uint64 // write index
	tail  atomic.Uint64 // read index
}

// Push inserts a frame into the ring buffer.
// Returns false if the buffer is full (frame dropped).
func (rb *Buffer) Push(f DataFrame) bool {
	h := rb.head.Load()
	next := (h + 1) & (RingSize - 1)
	if next == rb.tail.Load() {
		return false // full → drop
	}
	rb.slots[h] = f
	rb.head.Store(next)
	return true
}

// Pop removes and returns the oldest frame.
// Returns false if the buffer is empty.
func (rb *Buffer) Pop() (DataFrame, bool) {
	t := rb.tail.Load()
	if t == rb.head.Load() {
		return DataFrame{}, false // empty
	}
	f := rb.slots[t]
	rb.tail.Store((t + 1) & (RingSize - 1))
	return f, true
}

// Len returns the approximate number of items currently in the buffer.
func (rb *Buffer) Len() int {
	h := rb.head.Load()
	t := rb.tail.Load()
	if h >= t {
		return int(h - t)
	}
	return int(RingSize - t + h)
}
