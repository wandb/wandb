package nfs

import (
	"log/slog"
	"sync"
	"time"
)

// AuditEvent represents an access event to be logged.
type AuditEvent struct {
	Timestamp  time.Time
	ClientHost string
	ClientUID  uint32
	ClientGID  uint32
	Operation  string // "connect", "stat", "open", "readdir", "readlink"
	Path       string
	Success    bool
	Error      string
}

// AuditLogger records access to files/folders.
type AuditLogger struct {
	mu     sync.Mutex
	logger *slog.Logger
}

// NewAuditLogger creates a new audit logger.
func NewAuditLogger(logger *slog.Logger) *AuditLogger {
	return &AuditLogger{
		logger: logger,
	}
}

// LogAccess records an access event.
func (a *AuditLogger) LogAccess(event AuditEvent) {
	a.mu.Lock()
	defer a.mu.Unlock()

	if event.Timestamp.IsZero() {
		event.Timestamp = time.Now()
	}

	attrs := []any{
		"operation", event.Operation,
		"path", event.Path,
		"success", event.Success,
	}

	if event.ClientHost != "" {
		attrs = append(attrs, "client_host", event.ClientHost)
	}
	if event.ClientUID != 0 {
		attrs = append(attrs, "client_uid", event.ClientUID)
	}
	if event.ClientGID != 0 {
		attrs = append(attrs, "client_gid", event.ClientGID)
	}
	if event.Error != "" {
		attrs = append(attrs, "error", event.Error)
	}

	a.logger.Info("nfs_access", attrs...)
}

// LogConnect logs a client connection.
func (a *AuditLogger) LogConnect(host string, uid, gid uint32) {
	a.LogAccess(AuditEvent{
		ClientHost: host,
		ClientUID:  uid,
		ClientGID:  gid,
		Operation:  "connect",
		Path:       "/",
		Success:    true,
	})
}

// LogStat logs a stat operation.
func (a *AuditLogger) LogStat(host string, uid, gid uint32, path string, err error) {
	event := AuditEvent{
		ClientHost: host,
		ClientUID:  uid,
		ClientGID:  gid,
		Operation:  "stat",
		Path:       path,
		Success:    err == nil,
	}
	if err != nil {
		event.Error = err.Error()
	}
	a.LogAccess(event)
}

// LogOpen logs an open operation.
func (a *AuditLogger) LogOpen(host string, uid, gid uint32, path string, err error) {
	event := AuditEvent{
		ClientHost: host,
		ClientUID:  uid,
		ClientGID:  gid,
		Operation:  "open",
		Path:       path,
		Success:    err == nil,
	}
	if err != nil {
		event.Error = err.Error()
	}
	a.LogAccess(event)
}

// LogReaddir logs a readdir operation.
func (a *AuditLogger) LogReaddir(host string, uid, gid uint32, path string, err error) {
	event := AuditEvent{
		ClientHost: host,
		ClientUID:  uid,
		ClientGID:  gid,
		Operation:  "readdir",
		Path:       path,
		Success:    err == nil,
	}
	if err != nil {
		event.Error = err.Error()
	}
	a.LogAccess(event)
}

// LogReadlink logs a readlink operation.
func (a *AuditLogger) LogReadlink(host string, uid, gid uint32, path string, err error) {
	event := AuditEvent{
		ClientHost: host,
		ClientUID:  uid,
		ClientGID:  gid,
		Operation:  "readlink",
		Path:       path,
		Success:    err == nil,
	}
	if err != nil {
		event.Error = err.Error()
	}
	a.LogAccess(event)
}
