package apitest

import (
	"io"
	"net/http"
	"net/http/httptest"
	"slices"
	"sync"
)

type RecordingServer struct {
	sync.Mutex
	*httptest.Server

	requests []RequestCopy
}

// All requests recorded by the server.
func (s *RecordingServer) Requests() []RequestCopy {
	s.Lock()
	defer s.Unlock()
	return slices.Clone(s.requests)
}

type RecordingServerOption func(*RecordingServerConfig)

type RecordingServerConfig struct {
	handlerFunc http.HandlerFunc
}

func WithHandlerFunc(handler http.HandlerFunc) RecordingServerOption {
	return func(rs *RecordingServerConfig) {
		rs.handlerFunc = handler
	}
}

// Returns a server that records all requests made to it.
func NewRecordingServer(opts ...RecordingServerOption) *RecordingServer {
	rs := &RecordingServer{
		requests: make([]RequestCopy, 0),
	}

	rsConfig := &RecordingServerConfig{}
	for _, opt := range opts {
		opt(rsConfig)
	}

	rs.Server = httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			body, _ := io.ReadAll(r.Body)

			rs.Lock()
			defer rs.Unlock()

			rs.requests = append(rs.requests,
				RequestCopy{
					Method: r.Method,
					URL:    r.URL,
					Body:   body,
					Header: r.Header,
				})

			if rsConfig.handlerFunc != nil {
				rsConfig.handlerFunc(w, r)
			} else {
				_, _ = w.Write([]byte("OK"))
			}
		}),
	)

	return rs
}
