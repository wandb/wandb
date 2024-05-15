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

type Connection struct {
	ctx    context.Context
	cancel context.CancelFunc
	net.Conn
}

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

func (c *Connection) Close() error {
	err := c.Conn.Close()
	if err != nil {
		return fmt.Errorf("error closing connection: %w", err)
	}
	return nil
}

// Send sends a message to the server.
func (c *Connection) Send(msg proto.Message) error {
	data, err := proto.Marshal(msg)
	if err != nil {
		return fmt.Errorf("error marshaling message: %w", err)
	}
	writer := bufio.NewWriterSize(c, 16384)

	header := server.Header{Magic: byte('W'), DataLength: uint32(len(data))}
	err = binary.Write(writer, binary.LittleEndian, &header)
	if err != nil {
		return fmt.Errorf("error writing header: %w", err)
	}
	if _, err = writer.Write(data); err != nil {
		return fmt.Errorf("error writing message: %w", err)
	}
	if err = writer.Flush(); err != nil {
		return fmt.Errorf("error flushing writer: %w", err)
	}
	return nil
}
