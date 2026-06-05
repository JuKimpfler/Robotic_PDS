package main

import (
"fmt"
"os"
"os/signal"
"syscall"
"time"
)

func main() {
fmt.Println("Starting Telemetry Go Backend...")

// Set GC tuning
os.Setenv("GOGC", "400")
os.Setenv("GOMEMLIMIT", "4GiB")

// Placeholder for starting UDP receiver, HTTP server, WS hub

sigChan := make(chan os.Signal, 1)
signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
<-sigChan

fmt.Println("Shutting down gracefully...")
time.Sleep(100 * time.Millisecond)
}
