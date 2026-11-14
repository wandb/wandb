package main

import (
	"syscall"
	"testing"
	"testing/synctest"
	"time"

	"github.com/wandb/wandb/core/pkg/server"
)

func TestShutdownOnSIGTERMWaitsForGracePeriod(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		srv := server.NewServer(server.ServerParams{})
		start := time.Now()
		shutdownOnSignal(srv, make(chan error), syscall.SIGTERM)
		if elapsed := time.Since(start); elapsed != 30*time.Second {
			t.Fatalf("shutdown took %v, want 30s", elapsed)
		}
	})
}

func TestShutdownOnSIGTERMReturnsWhenServerStops(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		srv := server.NewServer(server.ServerParams{})
		srvCh := make(chan error, 1)
		srvCh <- nil
		start := time.Now()
		shutdownOnSignal(srv, srvCh, syscall.SIGTERM)
		if elapsed := time.Since(start); elapsed != 0 {
			t.Fatalf("shutdown took %v after server stopped", elapsed)
		}
	})
}
