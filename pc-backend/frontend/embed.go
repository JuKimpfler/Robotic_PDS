// Package frontend embeds the built Vite assets from dist/ for the HTTP server.
package frontend

import "embed"

// Dist holds the production frontend (run `npm run build` in repo frontend/ first).
//
//go:embed all:dist
var Dist embed.FS
