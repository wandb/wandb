package connection

import (
	"bufio"
	"context"
	"encoding/binary"
	"fmt"
	"net"

	"github.com/wandb/wandb/core/pkg/server"
	"google.golang.org/protobuf/proto"
)

const (
	defaultBufSize = 16384
)

// Connection wraps a net.Conn with additional context and cancellation support
type Connection struct {
	ctx    context.Context
	cancel context.CancelFunc
	net.Conn
}

// New creates a new Connection to the specified address
func New(ctx context.Context, addr string) (*Connection, error) {
	conn, err := net.Dial("tcp", addr)
	if err != nil {
		err = fmt.Errorf("error connecting to server: %w", err)
		return nil, err
	}
	ctx, cancel := context.WithCancel(ctx)
	return &Connection{
		ctx:    ctx,
		cancel: cancel,
		Conn:   conn,
	}, nil
}

// Close terminates the connection
func (c *Connection) Close() error {
	err := c.Conn.Close()
	if err != nil {
		return fmt.Errorf("error closing connection: %w", err)
	}
	c.cancel()
	return nil
}

// Send marshals and sends a message to the server
func (c *Connection) Send(msg proto.Message) error {
	// TODO: improve robustness: handle timeouts, retries, etc.
	data, err := proto.Marshal(msg)
	if err != nil {
		return fmt.Errorf("error marshaling message: %w", err)
	}
	return c.send(data)
}

// send sends a message to the server
func (c *Connection) send(msg []byte) error {

	writer := bufio.NewWriterSize(c, defaultBufSize)

	// Create a header for the message.
	if err := binary.Write(writer, binary.LittleEndian,
		&server.Header{
			Magic:      byte('W'),
			DataLength: uint32(len(msg)),
		},
	); err != nil {
		return fmt.Errorf("error writing header: %w", err)
	}

	// Write the message to the server.
	if _, err := writer.Write(msg); err != nil {
		return fmt.Errorf("error writing message: %w", err)
	}

	// Flush the buffered writer to ensure all data is sent.
	if err := writer.Flush(); err != nil {
		return fmt.Errorf("error flushing writer: %w", err)
	}
	return nil
}
