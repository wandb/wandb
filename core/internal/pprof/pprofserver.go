package pprof

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"runtime/pprof"
	"runtime/trace"
	"strconv"
	"strings"
	"time"
)

// StartServer starts an HTTP server exposing the /debug/pprof/* endpoints
// that `go tool pprof` and `go tool trace` fetch.
//
// It does not use net/http/pprof, whose text/template dependency keeps the
// linker from removing unused exported methods from the binary.
//
// For safety, prefer binding explicitly to loopback (e.g. "127.0.0.1:6060" instead of ":6060").
func StartServer(addr string) (shutdown func(context.Context) error, err error) {
	if addr == "" {
		return nil, nil
	}

	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return nil, fmt.Errorf("listen %q: %w", addr, err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/debug/pprof/profile", serveCPUProfile)
	mux.HandleFunc("/debug/pprof/trace", serveTrace)
	mux.HandleFunc("/debug/pprof/", serveProfile)

	srv := &http.Server{
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		serveErr := srv.Serve(ln)
		if serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
			fmt.Fprintln(os.Stderr, "pprof: server error:", serveErr)
		}
	}()

	return srv.Shutdown, nil
}

// serveCPUProfile records a CPU profile for the requested number of seconds.
func serveCPUProfile(w http.ResponseWriter, r *http.Request) {
	if err := pprof.StartCPUProfile(w); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	wait(r, 30*time.Second)
	pprof.StopCPUProfile()
}

// serveTrace records an execution trace for the requested number of seconds.
func serveTrace(w http.ResponseWriter, r *http.Request) {
	if err := trace.Start(w); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	wait(r, time.Second)
	trace.Stop()
}

// serveProfile writes the runtime profile named by the path, such as heap or goroutine.
func serveProfile(w http.ResponseWriter, r *http.Request) {
	profile := pprof.Lookup(strings.TrimPrefix(r.URL.Path, "/debug/pprof/"))
	if profile == nil {
		http.NotFound(w, r)
		return
	}
	debug, _ := strconv.Atoi(r.URL.Query().Get("debug"))
	_ = profile.WriteTo(w, debug)
}

// wait blocks for the "seconds" query parameter, or the default, unless the
// request is canceled first.
func wait(r *http.Request, defaultDuration time.Duration) {
	d := defaultDuration
	seconds, err := strconv.ParseFloat(r.URL.Query().Get("seconds"), 64)
	if err == nil && seconds > 0 {
		d = time.Duration(seconds * float64(time.Second))
	}
	select {
	case <-time.After(d):
	case <-r.Context().Done():
	}
}
