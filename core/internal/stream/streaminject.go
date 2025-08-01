//go:build wireinject

package stream

import (
	"github.com/google/wire"
)

// InjectStream returns a new Stream.
func InjectStream(params StreamParams) *Stream {
	wire.Build(
		NewStream,
		wire.FieldsOf(
			&params,
			"Settings",
			"Sentry",
			"LogLevel",
		),
		openStreamLoggerFile,
		streamLogger,
	)
	return &Stream{}
}
