// Package channels — fsnotify hot-reload watcher.
package channels

import (
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
	"github.com/rs/zerolog/log"
)

// Watcher monitors a channels.csv file and atomically replaces the ChannelMap
// on change. Subscribers are notified via a callback.
type Watcher struct {
	mu          sync.RWMutex
	current     ChannelMap
	path        string
	debounceMs  int
	onChange    func(ChannelMap) // called with new map after successful reload
	stopCh      chan struct{}
}

// NewWatcher creates a Watcher for the given CSV path.
// debounceMs controls the minimum delay between reload events (default 500 ms).
// onChange is called (in a goroutine) each time the map is successfully reloaded.
func NewWatcher(path string, debounceMs int, onChange func(ChannelMap)) (*Watcher, error) {
	initial, err := LoadCSV(path)
	if err != nil {
		return nil, err
	}
	w := &Watcher{
		current:    initial,
		path:       path,
		debounceMs: debounceMs,
		onChange:   onChange,
		stopCh:     make(chan struct{}),
	}
	return w, nil
}

// Get returns the current ChannelMap (safe for concurrent reads).
func (w *Watcher) Get() ChannelMap {
	w.mu.RLock()
	defer w.mu.RUnlock()
	return w.current
}

// Start begins watching for file changes. Blocks until ctx is cancelled or Stop() is called.
func (w *Watcher) Start() error {
	fw, err := fsnotify.NewWatcher()
	if err != nil {
		return err
	}
	defer fw.Close()

	if err := fw.Add(w.path); err != nil {
		return err
	}

	log.Info().Str("path", w.path).Msg("channel watcher started")

	debounce := time.Duration(w.debounceMs) * time.Millisecond
	var timer *time.Timer

	for {
		select {
		case <-w.stopCh:
			return nil

		case event, ok := <-fw.Events:
			if !ok {
				return nil
			}
			if event.Has(fsnotify.Write) || event.Has(fsnotify.Create) {
				// Debounce: reset timer on each event
				if timer != nil {
					timer.Stop()
				}
				timer = time.AfterFunc(debounce, func() {
					w.reload()
				})
			}

		case err, ok := <-fw.Errors:
			if !ok {
				return nil
			}
			log.Error().Err(err).Msg("channel watcher error")
		}
	}
}

// Stop signals the watcher to stop.
func (w *Watcher) Stop() {
	close(w.stopCh)
}

func (w *Watcher) reload() {
	cm, err := LoadCSV(w.path)
	if err != nil {
		log.Error().Err(err).Str("path", w.path).Msg("channel map reload failed — retaining previous")
		return
	}

	// Atomic swap under write lock
	w.mu.Lock()
	w.current = cm
	w.mu.Unlock()

	log.Info().Int("channels", len(cm)).Msg("channel map hot-reloaded")

	if w.onChange != nil {
		go w.onChange(cm)
	}
}
