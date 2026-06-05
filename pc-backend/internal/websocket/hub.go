// Package websocket — WebSocket hub with non-blocking fan-out and sync.Pool encoding buffers.
package websocket

import (
	"net/http"
	"sync"
	"sync/atomic"

	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
	"telemetry/internal/channels"
	"telemetry/internal/metrics"
)

// Client represents a single connected WebSocket client.
type Client struct {
	conn   *websocket.Conn
	send   chan []byte // buffered, cap 32
	hub    *Hub
	isJSON bool
}

// Hub manages all connected WebSocket clients and broadcasts frames.
type Hub struct {
	mu            sync.RWMutex
	clients       map[*Client]struct{}
	maxClients    int
	dropped       atomic.Uint64
	GetChannelMap func() channels.ChannelMap
}

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 65536,
	CheckOrigin:     func(r *http.Request) bool { return true },
}

// encodePool pools []byte buffers used for encoding to avoid per-frame allocs.
var encodePool = sync.Pool{
	New: func() any { return make([]byte, 0, 4096) },
}

// New creates a new Hub with the given maximum client count.
func New(maxClients int) *Hub {
	return &Hub{
		clients:    make(map[*Client]struct{}),
		maxClients: maxClients,
	}
}

// ServeWS upgrades an HTTP connection to WebSocket and registers the client.
// query param ?format=json selects JSON encoding instead of MessagePack.
func (h *Hub) ServeWS(w http.ResponseWriter, r *http.Request) {
	h.mu.Lock()
	if len(h.clients) >= h.maxClients {
		h.mu.Unlock()
		http.Error(w, "max clients reached", http.StatusServiceUnavailable)
		return
	}
	h.mu.Unlock()

	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Error().Err(err).Msg("WS upgrade failed")
		return
	}

	isJSON := r.URL.Query().Get("format") == "json"
	c := &Client{conn: conn, send: make(chan []byte, 32), hub: h, isJSON: isJSON}

	// Send initial channel map push if available
	if h.GetChannelMap != nil {
		cm := h.GetChannelMap()
		data, err := SerializeChannelMap(cm)
		if err == nil {
			c.send <- data
		} else {
			log.Error().Err(err).Msg("failed to serialize initial channel map")
		}
	}

	h.mu.Lock()
	h.clients[c] = struct{}{}
	metrics.WSClients.Set(float64(len(h.clients)))
	h.mu.Unlock()

	log.Info().Str("remote", conn.RemoteAddr().String()).Bool("json", isJSON).Msg("WS client connected")

	// Send initial channel map push
	// The caller or main loop will push the map, but we can also push it immediately on connect.
	// Wait, we will push the initial map in main.go or here if we have access to it.
	// We will handle that or push it in main.go upon connection.

	go c.writePump()
	c.readPump() // blocks until disconnect
}

// Broadcast sends raw bytes to all connected clients (e.g. status or channel map).
func (h *Hub) Broadcast(data []byte) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	for c := range h.clients {
		select {
		case c.send <- data:
		default:
			metrics.WSFramesDropped.Add(1)
			h.dropped.Add(1)
		}
	}
}

// BroadcastFrame serializes and sends a DataFrame to all clients,
// choosing the correct encoding (MessagePack or JSON) per client.
func (h *Hub) BroadcastFrame(f ring.DataFrame) {
	var msgpackData []byte
	var jsonData []byte
	var err error

	h.mu.RLock()
	defer h.mu.RUnlock()

	for c := range h.clients {
		var data []byte
		if c.isJSON {
			if jsonData == nil {
				jsonData, err = SerializeJSON(f)
				if err != nil {
					log.Error().Err(err).Msg("failed to serialize JSON frame")
					continue
				}
			}
			data = jsonData
		} else {
			if msgpackData == nil {
				msgpackData, err = SerializeMsgpack(f)
				if err != nil {
					log.Error().Err(err).Msg("failed to serialize Msgpack frame")
					continue
				}
			}
			data = msgpackData
		}

		select {
		case c.send <- data:
		default:
			metrics.WSFramesDropped.Add(1)
			h.dropped.Add(1)
		}
	}
}

// ClientCount returns the number of currently connected clients.
func (h *Hub) ClientCount() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.clients)
}

func (h *Hub) unregister(c *Client) {
	h.mu.Lock()
	delete(h.clients, c)
	metrics.WSClients.Set(float64(len(h.clients)))
	h.mu.Unlock()
	close(c.send)
	log.Info().Str("remote", c.conn.RemoteAddr().String()).Msg("WS client disconnected")
}

// readPump drains incoming messages (we don't expect any from browser — REST-only).
func (c *Client) readPump() {
	defer func() {
		c.hub.unregister(c)
		c.conn.Close()
	}()
	for {
		_, _, err := c.conn.ReadMessage()
		if err != nil {
			return
		}
	}
}

// writePump forwards messages from the send channel to the WebSocket.
func (c *Client) writePump() {
	defer c.conn.Close()
	for msg := range c.send {
		if err := c.conn.WriteMessage(websocket.BinaryMessage, msg); err != nil {
			return
		}
	}
}
