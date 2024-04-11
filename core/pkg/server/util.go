package server

import (
	"context"
	"fmt"
	"log/slog"
	"os"
)

func LogError(log *slog.Logger, msg string, err error) {
	log.LogAttrs(context.Background(),
		slog.LevelError,
		msg,
		slog.String("error", err.Error()))
}

func writePortFile(portFile string, port int) {
	tempFile := fmt.Sprintf("%s.tmp", portFile)
	f, err := os.Create(tempFile)
	if err != nil {
		LogError(slog.Default(), "fail create", err)
	}
	defer func(f *os.File) {
		_ = f.Close()
	}(f)

	if _, err = f.WriteString(fmt.Sprintf("sock=%d\n", port)); err != nil {
		LogError(slog.Default(), "fail write", err)
	}

	if _, err = f.WriteString("EOF"); err != nil {
		LogError(slog.Default(), "fail write EOF", err)
	}

	if err = f.Sync(); err != nil {
		LogError(slog.Default(), "fail sync", err)
	}

	if err = os.Rename(tempFile, portFile); err != nil {
		LogError(slog.Default(), "fail rename", err)
	}
	// slog.Info("wrote port file", "file", portFile, "port", port)
}
