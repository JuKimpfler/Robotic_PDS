// Package websocket — dedicated WebSocket server on port 9001 per §3.3 / §5.3.
package websocket

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"github.com/rs/zerolog/log"
)

// StartServer runs the WebSocket hub on the given port until ctx is cancelled.
// Serves only /stream — HTTP API and static frontend remain on port 8080.
func StartServer(ctx context.Context, port int, hub *Hub) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/stream", hub.ServeWS)

	addr := fmt.Sprintf(":%d", port)
	srv := &http.Server{Addr: addr, Handler: mux}

	go func() {
		<-ctx.Done()
		shutCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		srv.Shutdown(shutCtx)
	}()

	log.Info().Str("addr", addr).Msg("WebSocket server started")
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}
