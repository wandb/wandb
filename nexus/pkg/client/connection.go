package client

import (
	"bufio"
	"context"
	"encoding/binary"
	"fmt"

	"github.com/wandb/wandb/nexus/pkg/server"
	"github.com/wandb/wandb/nexus/pkg/service"

	"net"

	"google.golang.org/protobuf/proto"
)

// Connection is a connection to the server.
type Connection struct {
	// ctx is the context for the run
	ctx context.Context

	// Conn is the connection to the server
	net.Conn
}

// NewConnection creates a new connection to the server.
func NewConnection(ctx context.Context, addr string) (*Connection, error) {
	conn, err := net.Dial("tcp", addr)
	if err != nil {
		err = fmt.Errorf("error connecting to server: %w", err)
		return nil, err
	}
	connection := &Connection{
		ctx:  ctx,
		Conn: conn,
	}
	return connection, nil
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

func (c *Connection) Recv() {
	scanner := bufio.NewScanner(c.Conn)
	tokenizer := &server.Tokenizer{}
	scanner.Split(tokenizer.Split)
	for scanner.Scan() {
		msg := &service.ServerResponse{}
		err := proto.Unmarshal(scanner.Bytes(), msg)
		if err != nil {
			panic(err)
		}
		switch x := msg.ServerResponseType.(type) {
		case *service.ServerResponse_ResultCommunicate:
			switch x.ResultCommunicate.ResultType.(type) {
			case *service.Result_ExitResult:
				c.Close()
			default:
			}
		default:
		}
	}
}

// Close closes the connection.
func (c *Connection) Close() {
	err := c.Conn.Close()
	if err != nil {
		return
	}
}
