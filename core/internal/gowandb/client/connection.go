package gowandb

import (
	"bufio"
	"context"
	"encoding/binary"
	"fmt"
	"net"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/lib/shared"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

// Connection is a connection to the server.
type Connection struct {
	// ctx is the context for the run
	ctx context.Context

	// Conn is the connection to the server
	net.Conn

	// Mbox is the mailbox for the connection
	Mbox *Mailbox
}

// NewConnection creates a new connection to the server.
func NewConnection(ctx context.Context, addr string) (*Connection, error) {
	conn, err := net.Dial("tcp", addr)
	if err != nil {
		err = fmt.Errorf("error connecting to server: %w", err)
		return nil, err
	}
	mbox := NewMailbox()
	connection := &Connection{
		ctx:  ctx,
		Conn: conn,
		Mbox: mbox,
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

	header := shared.Header{Magic: byte('W'), DataLength: uint32(len(data))}
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
	tokenizer := &shared.Tokenizer{}
	scanner.Split(tokenizer.Split)
	for scanner.Scan() {
		msg := &pb.ServerResponse{}
		err := proto.Unmarshal(scanner.Bytes(), msg)
		if err != nil {
			panic(err)
		}
		switch x := msg.ServerResponseType.(type) {
		case *pb.ServerResponse_ResultCommunicate:
			c.Mbox.Respond(x.ResultCommunicate)
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
