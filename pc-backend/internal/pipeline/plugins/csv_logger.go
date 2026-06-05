// csv_logger.go — writes frames to a CSV file (off hot-path).
package plugins

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/rs/zerolog/log"
	"telemetry/internal/channels"
	"telemetry/internal/ring"
)

// CSVLogger writes each frame as a CSV row to a rotating log file.
// Writing happens in a background goroutine to stay off the hot path.
type CSVLogger struct {
	path    string
	mu      sync.Mutex
	file    *os.File
	writer  *bufio.Writer
	headerW bool
	queue   chan ring.DataFrame
	once    sync.Once
	stop    chan struct{}
}

// NewCSVLogger creates a CSVLogger writing to path.
func NewCSVLogger(path string) *CSVLogger {
	return &CSVLogger{
		path:  path,
		queue: make(chan ring.DataFrame, 1024),
		stop:  make(chan struct{}),
	}
}

func (*CSVLogger) Name() string { return "csv_logger" }

// Process enqueues the frame for background CSV writing.
// Never blocks — drops if queue is full.
func (l *CSVLogger) Process(f *ring.DataFrame, cm channels.ChannelMap) *ring.DataFrame {
	l.once.Do(func() { go l.writer_loop(cm) })
	select {
	case l.queue <- *f:
	default:
		// Queue full — drop (never block producer)
	}
	return f // pass through unchanged
}

// Close flushes and closes the CSV file.
func (l *CSVLogger) Close() {
	close(l.stop)
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.writer != nil {
		l.writer.Flush()
	}
	if l.file != nil {
		l.file.Close()
	}
}

func (l *CSVLogger) writer_loop(cm channels.ChannelMap) {
	if err := os.MkdirAll(filepath.Dir(l.path), 0o755); err != nil {
		log.Error().Err(err).Str("path", l.path).Msg("csv_logger: mkdir failed")
		return
	}
	f, err := os.OpenFile(l.path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		log.Error().Err(err).Str("path", l.path).Msg("csv_logger: open failed")
		return
	}
	l.mu.Lock()
	l.file = f
	l.writer = bufio.NewWriterSize(f, 64*1024)
	l.mu.Unlock()

	for {
		select {
		case <-l.stop:
			return
		case frame := <-l.queue:
			l.writeFrame(frame, cm)
		}
	}
}

func (l *CSVLogger) writeFrame(f ring.DataFrame, cm channels.ChannelMap) {
	l.mu.Lock()
	defer l.mu.Unlock()

	if !l.headerW {
		// Write header row
		headers := []string{"seq", "ts_us", "rate_hz"}
		for _, ch := range cm {
			headers = append(headers, ch.Name)
		}
		fmt.Fprintln(l.writer, strings.Join(headers, ","))
		l.headerW = true
	}

	row := make([]string, 3+len(f.Values))
	row[0] = fmt.Sprintf("%d", f.Seq)
	row[1] = fmt.Sprintf("%d", f.TsUs)
	row[2] = fmt.Sprintf("%.2f", f.RateHz)
	for i, v := range f.Values {
		row[3+i] = fmt.Sprintf("%g", v)
	}
	fmt.Fprintln(l.writer, strings.Join(row, ","))
}
