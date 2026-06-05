// Package udp — UDP receiver with zero-allocation hot path and sub-packet reassembly.
//
// Implements §5.2 (UDP sub-packet) and §3.3 (Windows socket tuning).
package udp

import (
	"encoding/binary"
	"net"
	"time"

	"github.com/rs/zerolog/log"
	"golang.org/x/sys/windows"
	"telemetry/internal/http"
	"telemetry/internal/metrics"
	"telemetry/internal/ring"
)

const (
	udpMagic        = 0xCDAB
	udpHeaderSize   = 12 // bytes before payload values[]
	udpCRCSize      = 2
	maxUDPPacket    = 65535
	reassemblyTTL   = 5 * time.Millisecond
	timeoutInterval = 100 // cleanup every N packets
)

// reassemblySlot holds the two sub-packets for one frame.
type reassemblySlot struct {
	pkts      [2][]byte
	arrivedAt time.Time
}

// subPacketHeader mirrors the UDP sub-packet header (§5.2), all little-endian.
type subPacketHeader struct {
	Magic        uint16
	FrameSeq     uint16
	ChannelCount uint16
	SubID        uint8
	SubTotal     uint8
	Offset       uint16
	PayloadCount uint16
}

// Receiver listens on UDP port and pushes assembled DataFrames into a ring buffer.
type Receiver struct {
	port   int
	ring   *ring.Buffer
	rpiIP  string      // discovered from last received packet
	stats  *http.Stats // shared stats for /api/stats
}

// New creates a Receiver targeting the given port.
func New(port int, rb *ring.Buffer, stats *http.Stats) *Receiver {
	return &Receiver{port: port, ring: rb, stats: stats}
}

// SourceIP returns the last seen source IP (the RPi's address).
func (rx *Receiver) SourceIP() string { return rx.rpiIP }

// Run starts the receive loop. Blocks until ctx is cancelled.
func (rx *Receiver) Run(stop <-chan struct{}) {
	conn, err := net.ListenUDP("udp4", &net.UDPAddr{Port: rx.port})
	if err != nil {
		log.Fatal().Err(err).Int("port", rx.port).Msg("UDP listen failed")
	}
	defer conn.Close()

	// Windows: set 8 MB receive buffer and TIME_CRITICAL thread priority
	if err := setSocketBuf(conn, 8*1024*1024); err != nil {
		log.Warn().Err(err).Msg("UDP SO_RCVBUF set failed (non-fatal)")
	}
	setThreadPriority()

	log.Info().Int("port", rx.port).Msg("UDP receiver started")

	// Pre-allocate everything — zero allocs in hot path
	buf := make([]byte, maxUDPPacket)
	reassembly := make(map[uint16]*reassemblySlot, 64)
	var frameRateMeasure frameRateMeter

	pktCount := 0

	for {
		select {
		case <-stop:
			return
		default:
		}

		conn.SetReadDeadline(time.Now().Add(10 * time.Millisecond))
		n, src, err := conn.ReadFromUDP(buf)
		if err != nil {
			if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
				continue
			}
			log.Error().Err(err).Msg("UDP read error")
			continue
		}

		metrics.UDPBytesTotal.Add(float64(n))
		if src != nil {
			rx.rpiIP = src.IP.String()
		}

		pktCount++

		hdr, ok := parseSubHeader(buf[:n])
		if !ok {
			continue
		}

		// Verify sub-packet CRC
		crcOffset := udpHeaderSize + int(hdr.PayloadCount)*4
		if n < crcOffset+udpCRCSize {
			metrics.CRCErrors.Add(1)
			if rx.stats != nil {
				rx.stats.CRCErrors.Add(1)
			}
			continue
		}
		if !crc16Ok(buf[:n], crcOffset) {
			metrics.CRCErrors.Add(1)
			if rx.stats != nil {
				rx.stats.CRCErrors.Add(1)
			}
			continue
		}

		// Store in reassembly map (copy payload — buf is reused)
		slot := reassembly[hdr.FrameSeq]
		if slot == nil {
			slot = &reassemblySlot{arrivedAt: time.Now()}
			reassembly[hdr.FrameSeq] = slot
		}
		pkt := make([]byte, n)
		copy(pkt, buf[:n])
		slot.pkts[hdr.SubID] = pkt

		// Both sub-packets received?
		if slot.pkts[0] != nil && slot.pkts[1] != nil {
			frame, ok := assembleFrame(slot, hdr.ChannelCount)
			if ok {
				frame.RateHz = float32(frameRateMeasure.tick())
				metrics.FrameRateHz.Set(float64(frame.RateHz))
				if !rx.ring.Push(frame) {
					metrics.FramesDropped.Add(1)
					if rx.stats != nil {
						rx.stats.FramesDropped.Add(1)
					}
				} else {
					metrics.FramesReceived.Add(1)
					if rx.stats != nil {
						rx.stats.FramesRx.Add(1)
						rx.stats.RateHz.Store(float64(frame.RateHz))
					}
				}
			}
			delete(reassembly, hdr.FrameSeq)
		}

		// Periodic stale reassembly cleanup (every 100 packets)
		if pktCount%timeoutInterval == 0 {
			now := time.Now()
			for seq, s := range reassembly {
				if now.Sub(s.arrivedAt) > reassemblyTTL {
					metrics.ReassemblyTimeouts.Add(1)
					metrics.FramesDropped.Add(1)
					if rx.stats != nil {
						rx.stats.FramesDropped.Add(1)
					}
					delete(reassembly, seq)
				}
			}
		}
	}
}

// parseSubHeader reads the 12-byte UDP sub-packet header from buf.
func parseSubHeader(buf []byte) (subPacketHeader, bool) {
	if len(buf) < udpHeaderSize {
		return subPacketHeader{}, false
	}
	hdr := subPacketHeader{
		Magic:        binary.LittleEndian.Uint16(buf[0:2]),
		FrameSeq:     binary.LittleEndian.Uint16(buf[2:4]),
		ChannelCount: binary.LittleEndian.Uint16(buf[4:6]),
		SubID:        buf[6],
		SubTotal:     buf[7],
		Offset:       binary.LittleEndian.Uint16(buf[8:10]),
		PayloadCount: binary.LittleEndian.Uint16(buf[10:12]),
	}
	if hdr.Magic != udpMagic || hdr.SubID > 1 {
		return subPacketHeader{}, false
	}
	return hdr, true
}

// assembleFrame combines two sub-packet payloads into a ring.DataFrame.
func assembleFrame(slot *reassemblySlot, channelCount uint16) (ring.DataFrame, bool) {
	values := make([]float32, channelCount)

	for _, pkt := range slot.pkts {
		if pkt == nil {
			return ring.DataFrame{}, false
		}
		offset := binary.LittleEndian.Uint16(pkt[8:10])
		count := binary.LittleEndian.Uint16(pkt[10:12])
		payload := pkt[udpHeaderSize : udpHeaderSize+int(count)*4]
		for i := uint16(0); i < count; i++ {
			bits := binary.LittleEndian.Uint32(payload[i*4 : i*4+4])
			values[offset+i] = float32FromBits(bits)
		}
	}

	// Read seq from first sub-packet
	seq := binary.LittleEndian.Uint16(slot.pkts[0][2:4])

	return ring.DataFrame{
		Seq:    seq,
		Values: values,
	}, true
}

// crc16Ok verifies CRC16-CCITT (poly 0x1021, init 0xFFFF) for buf[:crcOffset].
func crc16Ok(buf []byte, crcOffset int) bool {
	computed := crc16(buf[:crcOffset])
	stored := binary.LittleEndian.Uint16(buf[crcOffset : crcOffset+2])
	return computed == stored
}

func crc16(data []byte) uint16 {
	crc := uint16(0xFFFF)
	for _, b := range data {
		crc ^= uint16(b) << 8
		for i := 0; i < 8; i++ {
			if crc&0x8000 != 0 {
				crc = (crc << 1) ^ 0x1021
			} else {
				crc <<= 1
			}
		}
	}
	return crc
}

func float32FromBits(bits uint32) float32 {
	return *(*float32)((*[4]byte)((*[4]byte)(&[4]byte{
		byte(bits), byte(bits >> 8), byte(bits >> 16), byte(bits >> 24),
	})))
}

// ── Windows socket tuning ─────────────────────────────────────────────────────

func setSocketBuf(conn *net.UDPConn, size int) error {
	raw, err := conn.SyscallConn()
	if err != nil {
		return err
	}
	return raw.Control(func(fd uintptr) {
		windows.SetsockoptInt(windows.Handle(fd),
			windows.SOL_SOCKET, windows.SO_RCVBUF, size)
	})
}

func setThreadPriority() {
	// Set UDP receive goroutine to TIME_CRITICAL priority per §3.3
	_ = windows.SetThreadPriority(
		windows.CurrentThread(),
		windows.THREAD_PRIORITY_TIME_CRITICAL,
	)
}

// ── Frame rate meter ──────────────────────────────────────────────────────────

type frameRateMeter struct {
	last  time.Time
	count int
	rate  float64
}

func (m *frameRateMeter) tick() float64 {
	now := time.Now()
	m.count++
	if m.last.IsZero() {
		m.last = now
		return 0
	}
	elapsed := now.Sub(m.last).Seconds()
	if elapsed >= 1.0 {
		m.rate = float64(m.count) / elapsed
		m.count = 0
		m.last = now
	}
	return m.rate
}
