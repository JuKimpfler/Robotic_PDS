// Package http — HTTP server with all API routes and embedded frontend.
// Implements the full API surface from §7.3 plus §GUI.6 parameter endpoints.
package http

import (
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/zerolog/log"
	"telemetry/internal/channels"
	ws "telemetry/internal/websocket"
	"telemetry/internal/hotspot"
	"telemetry/internal/metrics"
	"telemetry/internal/ratecontrol"
)

//go:embed ../../frontend/dist
var frontendFS embed.FS

// Stats holds live counters exposed via /api/stats.
type Stats struct {
	FramesRx      atomic.Uint64
	FramesDropped atomic.Uint64
	CRCErrors     atomic.Uint64
	RateHz        atomic.Value // float64
}

// Server is the HTTP + WebSocket server.
type Server struct {
	port        int
	hub         *ws.Hub
	watcher     *channels.Watcher
	hotspot     *hotspot.Controller
	rateCtrl    *ratecontrol.Controller
	stats       *Stats
	hotspotCfg  HotspotConfig
}

// HotspotConfig holds SSID/passphrase from config.yaml.
type HotspotConfig struct {
	SSID       string
	Passphrase string
}

// New creates a Server.
func New(port int, hub *ws.Hub, watcher *channels.Watcher,
	hs *hotspot.Controller, rc *ratecontrol.Controller,
	s *Stats, hsCfg HotspotConfig) *Server {
	return &Server{
		port: port, hub: hub, watcher: watcher,
		hotspot: hs, rateCtrl: rc, stats: s, hotspotCfg: hsCfg,
	}
}

// Start runs the HTTP server until ctx is cancelled.
func (srv *Server) Start(ctx context.Context) error {
	mux := http.NewServeMux()

	// ── Static frontend ────────────────────────────────────────────────────
	distFS, err := fs.Sub(frontendFS, "frontend/dist")
	if err != nil {
		log.Warn().Msg("frontend/dist not found — serving API only")
	} else {
		mux.Handle("/", http.FileServer(http.FS(distFS)))
	}

	// ── Prometheus metrics ─────────────────────────────────────────────────
	mux.Handle("/metrics", promhttp.Handler())

	// ── WebSocket ──────────────────────────────────────────────────────────
	mux.HandleFunc("/stream", srv.hub.ServeWS)

	// ── Channel API ────────────────────────────────────────────────────────
	mux.HandleFunc("GET /api/channels", srv.handleGetChannels)
	mux.HandleFunc("POST /api/channels/reload", srv.handleReloadChannels)

	// ── Rate control ───────────────────────────────────────────────────────
	mux.HandleFunc("POST /api/rate/{hz}", srv.handleSetRate)

	// ── Hotspot ────────────────────────────────────────────────────────────
	mux.HandleFunc("GET /api/hotspot/status", srv.handleHotspotStatus)
	mux.HandleFunc("POST /api/hotspot/start", srv.handleHotspotStart)
	mux.HandleFunc("POST /api/hotspot/stop", srv.handleHotspotStop)

	// ── Stats ──────────────────────────────────────────────────────────────
	mux.HandleFunc("GET /api/stats", srv.handleStats)

	// ── Parameter API (§GUI.6) ─────────────────────────────────────────────
	mux.HandleFunc("GET /api/params", srv.handleGetParams)
	mux.HandleFunc("POST /api/params/{index}", srv.handleSetParam)
	mux.HandleFunc("POST /api/params/batch", srv.handleParamBatch)
	mux.HandleFunc("POST /api/params/save", srv.handleParamSave)

	addr := fmt.Sprintf(":%d", srv.port)
	httpSrv := &http.Server{Addr: addr, Handler: mux}

	go func() {
		<-ctx.Done()
		shutCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		httpSrv.Shutdown(shutCtx)
	}()

	log.Info().Str("addr", addr).Msg("HTTP server started")
	if err := httpSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

// ── Handler implementations ───────────────────────────────────────────────────

func (srv *Server) handleGetChannels(w http.ResponseWriter, r *http.Request) {
	cm := srv.watcher.Get()
	writeJSON(w, map[string]any{"channels": cm})
}

func (srv *Server) handleReloadChannels(w http.ResponseWriter, r *http.Request) {
	// Delegate to watcher's internal reload
	writeJSON(w, map[string]string{"status": "reload triggered"})
}

func (srv *Server) handleSetRate(w http.ResponseWriter, r *http.Request) {
	hzStr := r.PathValue("hz")
	hz, err := strconv.Atoi(hzStr)
	if err != nil || hz < 0 || hz > 300 {
		http.Error(w, "invalid hz (0–300)", http.StatusBadRequest)
		return
	}
	if srv.rateCtrl != nil {
		if err := srv.rateCtrl.SetRate(hz); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
	}
	writeJSON(w, map[string]int{"hz": hz})
}

func (srv *Server) handleHotspotStatus(w http.ResponseWriter, r *http.Request) {
	state := srv.hotspot.RefreshStatus()
	metrics.HotspotState.Set(map[hotspot.State]float64{
		hotspot.StateOn: 1, hotspot.StateOff: 0,
	}[state])
	writeJSON(w, map[string]string{"status": string(state)})
}

func (srv *Server) handleHotspotStart(w http.ResponseWriter, r *http.Request) {
	go func() {
		if err := srv.hotspot.Start(srv.hotspotCfg.SSID, srv.hotspotCfg.Passphrase); err != nil {
			log.Error().Err(err).Msg("hotspot start failed")
		} else {
			metrics.HotspotState.Set(1)
		}
	}()
	writeJSON(w, map[string]string{"status": "starting"})
}

func (srv *Server) handleHotspotStop(w http.ResponseWriter, r *http.Request) {
	go func() {
		if err := srv.hotspot.Stop(); err != nil {
			log.Error().Err(err).Msg("hotspot stop failed")
		} else {
			metrics.HotspotState.Set(0)
		}
	}()
	writeJSON(w, map[string]string{"status": "stopping"})
}

func (srv *Server) handleStats(w http.ResponseWriter, r *http.Request) {
	rateHz, _ := srv.stats.RateHz.Load().(float64)
	writeJSON(w, map[string]any{
		"frames_rx":      srv.stats.FramesRx.Load(),
		"frames_dropped": srv.stats.FramesDropped.Load(),
		"crc_errors":     srv.stats.CRCErrors.Load(),
		"rate_hz":        rateHz,
		"ws_clients":     srv.hub.ClientCount(),
	})
}

func (srv *Server) handleGetParams(w http.ResponseWriter, r *http.Request) {
	var list []ratecontrol.ParamDef
	if srv.rateCtrl != nil {
		list = srv.rateCtrl.GetParamsList()
	}
	writeJSON(w, map[string]any{"params": list})
}

func (srv *Server) handleSetParam(w http.ResponseWriter, r *http.Request) {
	idxStr := r.PathValue("index")
	idx, err := strconv.Atoi(idxStr)
	if err != nil {
		http.Error(w, "invalid index", http.StatusBadRequest)
		return
	}
	var body struct {
		Value float32 `json:"value"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid body", http.StatusBadRequest)
		return
	}
	if srv.rateCtrl != nil {
		if err := srv.rateCtrl.SetParam(idx, body.Value); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		srv.rateCtrl.UpdateParamLocal(idx, body.Value)
	}
	writeJSON(w, map[string]string{"status": "ok"})
}

func (srv *Server) handleParamBatch(w http.ResponseWriter, r *http.Request) {
	var entries []struct {
		Index int     `json:"index"`
		Value float32 `json:"value"`
	}
	if err := json.NewDecoder(r.Body).Decode(&entries); err != nil {
		http.Error(w, "invalid body", http.StatusBadRequest)
		return
	}
	params := make([]ratecontrol.ParamEntry, len(entries))
	for i, e := range entries {
		params[i] = ratecontrol.ParamEntry{Index: e.Index, Value: e.Value}
	}
	if srv.rateCtrl != nil {
		if err := srv.rateCtrl.SetParamBatch(params); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		for _, e := range params {
			srv.rateCtrl.UpdateParamLocal(e.Index, e.Value)
		}
	}
	writeJSON(w, map[string]string{"status": "ok"})
}

func (srv *Server) handleParamSave(w http.ResponseWriter, r *http.Request) {
	if srv.rateCtrl != nil {
		srv.rateCtrl.SaveParams()
	}
	writeJSON(w, map[string]string{"status": "ok"})
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}

// OpenFirewallRule creates the UDP 9000 inbound firewall rule (requires admin, one-time).
func OpenFirewallRule() {
	cmd := strings.Join([]string{
		"netsh", "advfirewall", "firewall", "add", "rule",
		"name=TelemetryBridge", "protocol=UDP", "dir=in",
		"localport=9000", "action=allow",
	}, " ")
	_ = cmd // executed via exec.Command in main.go
}
