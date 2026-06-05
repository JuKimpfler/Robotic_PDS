package main

import (
	"context"
	"flag"
	"fmt"
	"math"
	"os"
	"os/exec"
	"os/signal"
	"runtime/debug"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"gopkg.in/yaml.v3"

	"telemetry/internal/channels"
	"telemetry/internal/hotspot"
	"telemetry/internal/http"
	"telemetry/internal/metrics"
	"telemetry/internal/pipeline"
	"telemetry/internal/pipeline/plugins"
	"telemetry/internal/ratecontrol"
	"telemetry/internal/ring"
	"telemetry/internal/udp"
	ws "telemetry/internal/websocket"
)

// Config mirrors the pc-backend/config.yaml structure
type Config struct {
	UDP struct {
		ListenPort          int  `yaml:"listen_port"`
		RecvBufferBytes     int  `yaml:"recv_buffer_bytes"`
		ReassemblyTimeoutMs int  `yaml:"reassembly_timeout_ms"`
		SplitFrames         bool `yaml:"split_frames"`
	} `yaml:"udp"`
	WebSocket struct {
		Port            int    `yaml:"port"`
		MaxClients      int    `yaml:"max_clients"`
		FrameDropPolicy string `yaml:"frame_drop_policy"`
	} `yaml:"websocket"`
	HTTP struct {
		Port int `yaml:"port"`
	} `yaml:"http"`
	Hotspot struct {
		SSID       string `yaml:"ssid"`
		Passphrase string `yaml:"passphrase"`
		AutoStart  bool   `yaml:"auto_start"`
	} `yaml:"hotspot"`
	ChannelMap struct {
		Path             string `yaml:"path"`
		XlsxImportPath   string `yaml:"xlsx_import_path"`
		ReloadDebounceMs int    `yaml:"reload_debounce_ms"`
	} `yaml:"channel_map"`
	RateControl struct {
		Enabled       bool   `yaml:"enabled"`
		SerialPort    string `yaml:"serial_port"`
		Baud          int    `yaml:"baud"`
		DefaultRateHz int    `yaml:"default_rate_hz"`
	} `yaml:"rate_control"`
	RingBuffer struct {
		Size int `yaml:"size"`
	} `yaml:"ring_buffer"`
	Pipeline struct {
		QuantizeFloat16 bool `yaml:"quantize_float16"`
		Plugins         []struct {
			Name    string `yaml:"name"`
			Enabled bool   `yaml:"enabled"`
			Path    string `yaml:"path,omitempty"`
			Window  int    `yaml:"window,omitempty"`
		} `yaml:"plugins"`
	} `yaml:"pipeline"`
	Performance struct {
		GOGC              int    `yaml:"gogc"`
		GOMemlimit        string `yaml:"gomemlimit"`
		UDPThreadPriority string `yaml:"udp_thread_priority"`
	} `yaml:"performance"`
	Logging struct {
		Level  string `yaml:"level"`
		Format string `yaml:"format"`
	} `yaml:"logging"`
}

func main() {
	// ── Command Line Flags ──────────────────────────────────────────────────
	configPath := flag.String("config", "config.yaml", "Path to config.yaml file")
	simulate := flag.Bool("simulate", false, "Enable simulation mode (generates synthetic frames without RPi/Teensy hardware)")
	flag.Parse()

	// ── Load Configuration ──────────────────────────────────────────────────
	cfg, err := loadConfig(*configPath)
	if err != nil {
		fmt.Printf("Error loading config: %v\n", err)
		os.Exit(1)
	}

	// ── Configure Logging ────────────────────────────────────────────────────
	setupLogger(cfg.Logging.Format, cfg.Logging.Level)
	log.Info().Str("config", *configPath).Bool("simulate", *simulate).Msg("starting telemetry backend")

	// ── Windows Firewall Rule (Attempt auto-add) ───────────────────────────
	if !*simulate {
		go tryAddFirewallRule()
	}

	// ── GC / Memory Tuning ──────────────────────────────────────────────────
	gogc := 400
	if cfg.Performance.GOGC > 0 {
		gogc = cfg.Performance.GOGC
	}
	debug.SetGCPercent(gogc)

	memLimit := int64(4 * 1024 * 1024 * 1024) // 4 GiB
	if cfg.Performance.GOMemlimit != "" {
		if val, err := parseBytes(cfg.Performance.GOMemlimit); err == nil {
			memLimit = val
		}
	}
	debug.SetMemoryLimit(memLimit)
	log.Info().Int("gogc", gogc).Int64("memLimit_bytes", memLimit).Msg("runtime gc/memory limits configured")

	// ── Channels Map Loading & Watching ─────────────────────────────────────
	// Convert xlsx to csv first if configured
	if cfg.ChannelMap.XlsxImportPath != "" {
		log.Info().Str("xlsx", cfg.ChannelMap.XlsxImportPath).Str("csv", cfg.ChannelMap.Path).Msg("importing channel definitions from XLSX")
		if _, err := channels.ImportXLSX(cfg.ChannelMap.XlsxImportPath, cfg.ChannelMap.Path); err != nil {
			log.Error().Err(err).Msg("failed to import XLSX channel definitions — trying to load existing CSV")
		}
	}

	// Create channels watcher
	hub := ws.New(cfg.WebSocket.MaxClients)
	watcher, err := channels.NewWatcher(cfg.ChannelMap.Path, cfg.ChannelMap.ReloadDebounceMs, func(cm channels.ChannelMap) {
		log.Info().Int("count", len(cm)).Msg("channel map changed, broadcasting to clients")
		data, err := ws.SerializeChannelMap(cm)
		if err != nil {
			log.Error().Err(err).Msg("failed to serialize channel map")
			return
		}
		hub.BroadcastJSON(data)
	})
	if err != nil {
		log.Fatal().Err(err).Str("path", cfg.ChannelMap.Path).Msg("failed to load initial channel map")
	}

	// Attach watcher state retrieval to hub so new connections get the map
	hub.GetChannelMap = func() channels.ChannelMap {
		return watcher.Get()
	}

	// ── Hotspot Controller ───────────────────────────────────────────────────
	hsCtrl := hotspot.New()
	if cfg.Hotspot.AutoStart && !*simulate {
		log.Info().Str("ssid", cfg.Hotspot.SSID).Msg("starting Windows Mobile Hotspot")
		go func() {
			if err := hsCtrl.Start(cfg.Hotspot.SSID, cfg.Hotspot.Passphrase); err != nil {
				log.Error().Err(err).Msg("failed to auto-start hotspot")
			}
		}()
	}

	// ── Rate Control (Teensy UART) ───────────────────────────────────────────
	var rcCtrl *ratecontrol.Controller
	var rcPort string
	if *simulate {
		rcPort = "MOCK"
	} else if cfg.RateControl.Enabled {
		rcPort = cfg.RateControl.SerialPort
	}
	rcCtrl = ratecontrol.New(rcPort, cfg.RateControl.Baud)
	if err := rcCtrl.Open(); err != nil {
		log.Error().Err(err).Str("port", rcPort).Msg("failed to open serial rate control connection")
	} else {
		defer rcCtrl.Close()
		// Load parameters.csv list if present
		paramsList, err := ratecontrol.LoadParameters("parameters.csv")
		if err != nil {
			log.Warn().Err(err).Msg("could not load parameters.csv definition file")
		} else {
			rcCtrl.SetParamsList(paramsList)
			log.Info().Int("count", len(paramsList)).Msg("loaded tunable parameters list")
		}
		if *simulate {
			_ = rcCtrl.SetRate(cfg.RateControl.DefaultRateHz)
		}
	}

	hub.GetParamMap = func() []ratecontrol.ParamDef {
		if rcCtrl != nil {
			return rcCtrl.GetParamsList()
		}
		return nil
	}

	// ── Ring Buffer ──────────────────────────────────────────────────────────
	rb := &ring.Buffer{} // Size is fixed to 1024 slots per RingSize constant

	// ── Pipeline & Plugins ───────────────────────────────────────────────────
	var pipePlugins []plugins.Plugin
	var csvLogPlugin *plugins.CSVLogger

	for _, p := range cfg.Pipeline.Plugins {
		if !p.Enabled {
			continue
		}
		switch p.Name {
		case "calibration":
			pipePlugins = append(pipePlugins, &plugins.Calibration{})
			log.Info().Msg("calibration plugin enabled")
		case "moving_average":
			pipePlugins = append(pipePlugins, plugins.NewMovingAverage(p.Window))
			log.Info().Int("window", p.Window).Msg("moving_average plugin enabled")
		case "csv_logger":
			csvLogPlugin = plugins.NewCSVLogger(p.Path)
			pipePlugins = append(pipePlugins, csvLogPlugin)
			log.Info().Str("path", p.Path).Msg("csv_logger plugin enabled")
		default:
			log.Warn().Str("name", p.Name).Msg("unknown plugin ignored")
		}
	}
	pipe := pipeline.New(pipePlugins)

	// ── Start Subsystems ─────────────────────────────────────────────────────
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// 1. Channel map file watcher
	go func() {
		if err := watcher.Start(); err != nil {
			log.Error().Err(err).Msg("watcher failed")
		}
	}()
	defer watcher.Stop()

	// 2. Data source (UDP receiver or Simulator)
	stopSource := make(chan struct{})
	defer close(stopSource)

	stats := &http.Stats{}
	var rpiIPFn func() string

	if *simulate {
		log.Info().Msg("running in simulator mode (synthetic frame generation)")
		rpiIPFn = func() string { return "127.0.0.1 (simulate)" }
		go runSimulator(stopSource, rb, rcCtrl, len(watcher.Get()), stats)
	} else {
		log.Info().Int("port", cfg.UDP.ListenPort).Msg("running in hardware receiver mode")
		rx := udp.New(cfg.UDP.ListenPort, rb, stats)
		rpiIPFn = rx.SourceIP
		go rx.Run(stopSource)
	}

	// 3. Pipeline processor worker (pops from ring buffer, runs pipeline, broadcasts)
	go runPipelineWorker(ctx.Done(), rb, pipe, hub, watcher, stats)

	// 4. HTTP and WebSocket Server
	srvConfig := http.HotspotConfig{
		SSID:       cfg.Hotspot.SSID,
		Passphrase: cfg.Hotspot.Passphrase,
	}
	server := http.New(cfg.HTTP.Port, hub, watcher, hsCtrl, rcCtrl, stats, srvConfig)

	go func() {
		if err := server.Start(ctx); err != nil {
			log.Fatal().Err(err).Msg("HTTP server failed")
		}
	}()

	// 4b. WebSocket server on dedicated port (§3.3: port 9001)
	go func() {
		if err := ws.StartServer(ctx, cfg.WebSocket.Port, hub); err != nil {
			log.Fatal().Err(err).Msg("WebSocket server failed")
		}
	}()

	// 5. Status publisher (broadcasts stats to WS clients at 1 Hz)
	go runStatusPublisher(ctx.Done(), hub, hsCtrl, stats, rpiIPFn)

	// ── Graceful Shutdown ────────────────────────────────────────────────────
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	sig := <-sigChan
	log.Info().Str("signal", sig.String()).Msg("shutting down pc-backend...")

	cancel() // Stop HTTP server and background loops
	if csvLogPlugin != nil {
		csvLogPlugin.Close()
	}

	// Note: Mobile Hotspot is NOT shut down automatically (intentional per spec)
	log.Info().Msg("pc-backend exited cleanly")
}

// loadConfig reads config.yaml
func loadConfig(path string) (*Config, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var c Config
	if err := yaml.Unmarshal(b, &c); err != nil {
		return nil, err
	}
	return &c, nil
}

// setupLogger sets log formats
func setupLogger(format, level string) {
	lvl, err := zerolog.ParseLevel(level)
	if err != nil {
		lvl = zerolog.InfoLevel
	}
	zerolog.SetGlobalLevel(lvl)

	if strings.ToLower(format) == "text" {
		log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: time.RFC3339})
	}
}

// tryAddFirewallRule adds the UDP 9000 inbound rule. Ignored if fails.
func tryAddFirewallRule() {
	cmd := exec.Command("netsh", "advfirewall", "firewall", "add", "rule",
		"name=TelemetryBridge", "protocol=UDP", "dir=in",
		"localport=9000", "action=allow")
	if err := cmd.Run(); err != nil {
		log.Debug().Err(err).Msg("failed to run netsh firewall rule creation (normal if not admin)")
	} else {
		log.Info().Msg("Windows firewall rule verified/added for UDP port 9000")
	}
}

// parseBytes parses strings like "4GiB" or "256MiB" into bytes
func parseBytes(s string) (int64, error) {
	s = strings.ToUpper(strings.TrimSpace(s))
	if strings.HasSuffix(s, "GIB") {
		val, err := strconv.ParseInt(strings.TrimSuffix(s, "GIB"), 10, 64)
		return val * 1024 * 1024 * 1024, err
	}
	if strings.HasSuffix(s, "MIB") {
		val, err := strconv.ParseInt(strings.TrimSuffix(s, "MIB"), 10, 64)
		return val * 1024 * 1024, err
	}
	return strconv.ParseInt(s, 10, 64)
}

// runSimulator generates frame data for --simulate mode
func runSimulator(stop <-chan struct{}, rb *ring.Buffer, rc *ratecontrol.Controller, channelCount int, stats *http.Stats) {
	ticker := time.NewTicker(10 * time.Millisecond) // 100 Hz baseline
	defer ticker.Stop()

	seq := uint16(0)
	startTime := time.Now()

	for {
		select {
		case <-stop:
			return
		case <-ticker.C:
			hz := rc.GetRate()
			if hz <= 0 {
				time.Sleep(10 * time.Millisecond)
				continue
			}

			// Dynamically adjust rate
			ticker.Reset(time.Second / time.Duration(hz))

			tsUs := uint32(time.Since(startTime).Microseconds())
			vals := make([]float32, channelCount)
			for i := 0; i < channelCount; i++ {
				if i == 7 || i == 8 {
					vals[i] = 9898.0 // dummy sentinel
				} else {
					freq := 1.0 + float64(i%10)*0.5
					amp := 500.0 + float64(i%4)*500.0
					vals[i] = float32(amp * math.Sin(2.0*math.Pi*freq*float64(tsUs)*1e-6 + float64(i)*0.1))
				}
			}

			frame := ring.DataFrame{
				Seq:    seq,
				TsUs:   tsUs,
				Values: vals,
				RateHz: float32(hz),
			}
			seq++

			metrics.FrameRateHz.Set(float64(hz))
			if rb.Push(frame) {
				metrics.FramesReceived.Add(1)
				if stats != nil {
					stats.FramesRx.Add(1)
					stats.RateHz.Store(float64(hz))
				}
			} else {
				metrics.FramesDropped.Add(1)
				if stats != nil {
					stats.FramesDropped.Add(1)
				}
			}
		}
	}
}

// runPipelineWorker drains ring buffer, processes, and broadcasts
func runPipelineWorker(stop <-chan struct{}, rb *ring.Buffer, pipe *pipeline.Pipeline, hub *ws.Hub, watcher *channels.Watcher, stats *http.Stats) {
	for {
		select {
		case <-stop:
			return
		default:
			frame, ok := rb.Pop()
			if !ok {
				// Sleep a tiny bit to stay cpu friendly
				time.Sleep(500 * time.Microsecond)
				continue
			}

			cm := watcher.Get()
			processed := pipe.Process(frame, cm)
			if processed != nil {
				hub.BroadcastFrame(*processed)
			}
		}
	}
}

// runStatusPublisher broadcasts connection status & stats at 1 Hz
func runStatusPublisher(stop <-chan struct{}, hub *ws.Hub, hsCtrl *hotspot.Controller, stats *http.Stats, rpiIPFn func() string) {
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-stop:
			return
		case <-ticker.C:
			if hub.ClientCount() == 0 {
				continue
			}
			hsState := string(hsCtrl.Status())
			rateHz, _ := stats.RateHz.Load().(float64)

			rpiIP := "—"
			if rpiIPFn != nil {
				if ip := rpiIPFn(); ip != "" {
					rpiIP = ip
				}
			}

			msg := ws.StatusMsg{
				Hotspot:       hsState,
				RpiIP:         rpiIP,
				FramesRx:      stats.FramesRx.Load(),
				FramesDropped: stats.FramesDropped.Load(),
				CRCErrors:     stats.CRCErrors.Load(),
				RateHz:        rateHz,
			}
			data, err := ws.SerializeStatus(msg)
			if err == nil {
				hub.BroadcastJSON(data)
			}
		}
	}
}
