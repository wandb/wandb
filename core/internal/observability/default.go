package observability

import (
	"sync/atomic"
)

var defaultLoggerPath atomic.Value

func SetDefaultLoggerPath(path string) {
	if path == "" {
		return
	}
	defaultLoggerPath.Store(path)
}

func GetDefaultLoggerPath() (string, bool) {
	if path, ok := defaultLoggerPath.Load().(string); ok {
		return path, ok
	}
	return "", false
}
