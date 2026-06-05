// Package ratecontrol — UART serial command channel to Teensy for frame rate and parameter control.
// Implements §6.3 (rate control) and §GUI.6 (parameter protocol).
package ratecontrol

import (
	"bufio"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/rs/zerolog/log"
	"go.bug.st/serial"
)

// Controller manages the serial connection to the Teensy.
type Controller struct {
	mu       sync.Mutex
	port     serial.Port
	scanner  *bufio.Scanner
	portName string
	baud     int
	params   []ParamDef
	rateHz   int
}

// New creates a Controller for the given serial port.
func New(portName string, baud int) *Controller {
	return &Controller{portName: portName, baud: baud, rateHz: 100}
}

// Open opens the serial port. Must be called before any commands.
func (c *Controller) Open() error {
	if c.portName == "MOCK" || c.portName == "" {
		log.Info().Str("port", c.portName).Msg("ratecontrol: mock serial port active")
		return nil
	}
	mode := &serial.Mode{BaudRate: c.baud}
	p, err := serial.Open(c.portName, mode)
	if err != nil {
		return fmt.Errorf("ratecontrol: open %s: %w", c.portName, err)
	}
	c.mu.Lock()
	c.port = p
	c.scanner = bufio.NewScanner(p)
	c.mu.Unlock()
	log.Info().Str("port", c.portName).Int("baud", c.baud).Msg("serial port opened")
	return nil
}

// Close closes the serial port.
func (c *Controller) Close() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.port != nil {
		c.port.Close()
		c.port = nil
	}
}

// SetRate sends a RATE:hz\n command and waits for RATE_ACK.
func (c *Controller) SetRate(hz int) error {
	c.mu.Lock()
	c.rateHz = hz
	c.mu.Unlock()
	cmd := fmt.Sprintf("RATE:%d\n", hz)
	ack := fmt.Sprintf("RATE_ACK:%d", hz)
	return c.sendAndAwait(cmd, ack, 500*time.Millisecond)
}

// GetRate returns the current target frame rate.
func (c *Controller) GetRate() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.rateHz
}

// SetParam sends PARAM_SET:index:value\n and awaits PARAM_ACK:OK.
func (c *Controller) SetParam(index int, value float32) error {
	cmd := fmt.Sprintf("PARAM_SET:%d:%.6g\n", index, value)
	return c.sendAndAwait(cmd, "PARAM_ACK:OK", 500*time.Millisecond)
}

// SetParamBatch sends a PARAM_BATCH command with up to 50 index:value pairs.
func (c *Controller) SetParamBatch(params []ParamEntry) error {
	if len(params) == 0 {
		return nil
	}
	parts := make([]string, len(params))
	for i, p := range params {
		parts[i] = fmt.Sprintf("%d:%.6g", p.Index, p.Value)
	}
	cmd := fmt.Sprintf("PARAM_BATCH:%s\n", strings.Join(parts, ","))
	return c.sendAndAwait(cmd, "PARAM_ACK:OK", 2*time.Second)
}

// SaveParams sends PARAM_SAVE\n to persist to Teensy EEPROM.
func (c *Controller) SaveParams() error {
	return c.sendAndAwait("PARAM_SAVE\n", "PARAM_ACK:OK", 2*time.Second)
}

// LoadPreset sends PARAM_LOAD:slot\n.
func (c *Controller) LoadPreset(slot int) error {
	cmd := fmt.Sprintf("PARAM_LOAD:%d\n", slot)
	return c.sendAndAwait(cmd, "PARAM_ACK:OK", 2*time.Second)
}

// ParamEntry is a single index+value pair for batch operations.
type ParamEntry struct {
	Index int
	Value float32
}

// sendAndAwait writes a command and reads lines until it finds expectedPrefix or timeout.
func (c *Controller) sendAndAwait(cmd, expectedPrefix string, timeout time.Duration) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.portName == "MOCK" || c.portName == "" {
		log.Info().Str("cmd", strings.Trim(cmd, "\r\n")).Msg("ratecontrol (mock): write")
		time.Sleep(5 * time.Millisecond)
		return nil
	}

	if c.port == nil {
		return fmt.Errorf("ratecontrol: port not open")
	}

	if _, err := c.port.Write([]byte(cmd)); err != nil {
		return fmt.Errorf("ratecontrol: write %q: %w", cmd, err)
	}

	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !c.scanner.Scan() {
			break
		}
		line := strings.TrimSpace(c.scanner.Text())
		if strings.HasPrefix(line, expectedPrefix) {
			return nil
		}
		if strings.HasPrefix(line, "PARAM_ACK:ERR") || strings.HasPrefix(line, "RATE_ACK:ERR") {
			return fmt.Errorf("ratecontrol: Teensy error: %s", line)
		}
	}
	return fmt.Errorf("ratecontrol: timeout waiting for %q", expectedPrefix)
}
