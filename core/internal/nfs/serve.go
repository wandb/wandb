package nfs

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/smallfz/libnfs-go/auth"
	"github.com/smallfz/libnfs-go/backend"
	"github.com/smallfz/libnfs-go/fs"
	"github.com/smallfz/libnfs-go/server"
)

// ServeOptions holds options for the NFS server.
type ServeOptions struct {
	ListenAddr  string
	ProjectPath *ProjectPath
}

// Serve starts the NFS server.
func Serve(ctx context.Context, opts ServeOptions) error {
	cfg, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("loading config: %w", err)
	}

	client, err := NewGraphQLClient(cfg)
	if err != nil {
		return fmt.Errorf("creating GraphQL client: %w", err)
	}

	// Create audit logger
	auditLogger := NewAuditLogger(slog.Default())

	// Factory function creates new FS per connection
	// This allows each connection to have its own credentials context
	fsFactory := func() fs.FS {
		return NewWandBFS(client, opts.ProjectPath, auditLogger)
	}

	// Use Unix auth to capture client credentials
	be := backend.New(fsFactory, auth.Unix)

	svr, err := server.NewServerTCP(opts.ListenAddr, be)
	if err != nil {
		return fmt.Errorf("creating server: %w", err)
	}

	slog.Info("Starting NFS server",
		"address", opts.ListenAddr,
		"project", fmt.Sprintf("%s/%s", opts.ProjectPath.Entity, opts.ProjectPath.Project),
	)

	// Start server in goroutine so we can handle context cancellation
	errCh := make(chan error, 1)
	go func() {
		errCh <- svr.Serve()
	}()

	select {
	case <-ctx.Done():
		slog.Info("Shutting down NFS server")
		return ctx.Err()
	case err := <-errCh:
		return err
	}
}
