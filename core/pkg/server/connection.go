package server

import (
	"bufio"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"sync"
	"sync/atomic"

	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/observability"

	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

const (
	messageSize    = 1024 * 1024            // 1MB message size
	maxMessageSize = 2 * 1024 * 1024 * 1024 // 2GB max message size
)

// Connection is the connection for a stream.
// It is a wrapper around the underlying connection
// It handles the incoming messages from the client
// and passes them to the stream
type Connection struct {
	// ctx is the context for the connection
	ctx context.Context

	// cancel is the cancel function for the connection
	cancel context.CancelFunc

	// conn is the underlying connection
	conn net.Conn

	// id is the unique id for the connection
	id string

	// inChan is the channel for incoming messages
	inChan chan *service.ServerRequest

	// outChan is the channel for outgoing messages
	outChan chan *service.ServerResponse

	// stream is the stream for the connection, each connection has a single stream
	// however, a stream can have multiple connections
	stream *Stream

	// closed indicates if the outChan is closed
	closed *atomic.Bool
}

// NewConnection creates a new connection
func NewConnection(
	ctx context.Context,
	cancel context.CancelFunc,
	conn net.Conn,
) *Connection {

	nc := &Connection{
		ctx:     ctx,
		cancel:  cancel,
		conn:    conn,
		id:      conn.RemoteAddr().String(), // TODO: check if this is properly unique
		inChan:  make(chan *service.ServerRequest, BufferSize),
		outChan: make(chan *service.ServerResponse, BufferSize),
		closed:  &atomic.Bool{},
	}
	return nc
}

// HandleConnection handles the connection by reading from the connection
// and passing the messages to the stream
// and writing messages from the stream to the connection
func (nc *Connection) HandleConnection() {
	slog.Info("connection: HandleConnection: created new connection",
		"connection", nc.id,
	)

	wg := sync.WaitGroup{}

	wg.Add(1)
	go func() {
		nc.readConnection()
		wg.Done()
	}()

	wg.Add(1)
	go func() {
		nc.handleServerRequest()
		wg.Done()
	}()

	wg.Add(1)
	go func() {
		nc.handleServerResponse()
		wg.Done()
	}()

	// context is cancelled when we receive a teardown message on any connection
	// this will trigger all connections to close since they all share the same context
	<-nc.ctx.Done()
	nc.Close()
	wg.Wait()

	slog.Info("connection: HandleConnection: connection closed",
		"connection", nc.id,
	)
}

// Close closes the connection
func (nc *Connection) Close() {
	slog.Debug("connection: Close: closing connection", "connection", nc.id)
	if err := nc.conn.Close(); err != nil {
		slog.Error("connection: Close: error closing connection",
			"error", err, "connection", nc.id,
		)
	}
	slog.Debug("connection: Close: closed connection", "connection", nc.id)
}

func (nc *Connection) Respond(resp *service.ServerResponse) {
	if nc.closed.Load() {
		// TODO: this is a bit of a hack, we should probably handle this better
		//       and not send responses to closed connections
		slog.Error("connection: Respond: connection is closed",
			"connection", nc.id,
		)
		return
	}
	nc.outChan <- resp
	slog.Debug("connection: Respond: response sent",
		"connection", nc.id, "response", resp,
	)
}

// readConnection reads the streaming connection
// it reads raw bytes from the connection and parses them into protobuf messages
// it passes the messages to the inChan to be handled by handleServerRequest
// it closes the inChan when the connection is closed
func (nc *Connection) readConnection() {
	slog.Info("connection: readConnection: starting",
		"connection", nc.id,
	)
	scanner := bufio.NewScanner(nc.conn)
	buf := make([]byte, messageSize)
	scanner.Buffer(buf, maxMessageSize)
	tokenizer := &Tokenizer{}
	scanner.Split(tokenizer.Split)
	for scanner.Scan() {
		msg := &service.ServerRequest{}
		if err := proto.Unmarshal(scanner.Bytes(), msg); err != nil {
			slog.Error("connection: readConnection: unmarshalling error",
				"error", err, "address", nc.conn.RemoteAddr())
		} else {
			nc.inChan <- msg
		}
	}
	if scanner.Err() != nil && !errors.Is(scanner.Err(), net.ErrClosed) {
		panic(scanner.Err())
	}
	close(nc.inChan)
	slog.Info("connection: readConnection: finished",
		"connection", nc.id,
	)
}

// handleServerRequest handles outgoing messages from the server
// to the client, it writes the messages to the connection
// the client is responsible for reading and parsing the messages
func (nc *Connection) handleServerResponse() {
	slog.Info("connection: handleServerResponse: starting",
		"connection", nc.id,
	)
	for msg := range nc.outChan {
		out, err := proto.Marshal(msg)
		if err != nil {
			slog.Error(
				"connection: handleServerResponse: error marshalling message",
				"error", err, "connection", nc.id,
			)
			return
		}

		writer := bufio.NewWriter(nc.conn)
		header := Header{Magic: byte('W'), DataLength: uint32(len(out))}
		if err = binary.Write(writer, binary.LittleEndian, &header); err != nil {
			slog.Error("connection: handleServerResponse: error writing header",
				"error", err, "connection", nc.id,
			)
			return
		}
		if _, err = writer.Write(out); err != nil {
			slog.Error("connection: handleServerResponse: error writing msg",
				"error", err, "connection", nc.id,
			)
			return
		}

		if err = writer.Flush(); err != nil {
			slog.Error("connection: handleServerResponse:error flushing writer",
				"error", err, "connection", nc.id,
			)
			return
		}
	}
	slog.Info("connection: handleServerResponse: finished",
		"connection", nc.id,
	)
}

// handleServerRequest handles incoming messages from the client
// to the server, it passes the messages to the stream
func (nc *Connection) handleServerRequest() {
	slog.Info("connection: handleServerRequest: starting",
		"connection", nc.id,
	)
	for msg := range nc.inChan {
		slog.Debug("connection: handleServerRequest: handling server request",
			"message", msg, "connection", nc.id,
		)
		switch x := msg.ServerRequestType.(type) {
		case *service.ServerRequest_InformInit:
			nc.handleInformInit(x.InformInit)
		case *service.ServerRequest_InformStart:
			nc.handleInformStart(x.InformStart)
		case *service.ServerRequest_InformAttach:
			nc.handleInformAttach(x.InformAttach)
		case *service.ServerRequest_RecordPublish:
			nc.handleInformRecord(x.RecordPublish)
		case *service.ServerRequest_RecordCommunicate:
			nc.handleInformRecord(x.RecordCommunicate)
		case *service.ServerRequest_InformFinish:
			nc.handleInformFinish(x.InformFinish)
		case *service.ServerRequest_InformTeardown:
			nc.handleInformTeardown(x.InformTeardown)
		case nil:
			err := fmt.Errorf("ServerRequestType is nil type")
			slog.Error("connection: handleServerRequest:",
				"error", err, "connection", nc.id,
			)
			panic(err)
		default:
			err := fmt.Errorf("ServerRequestType is unknown, %T", x)
			slog.Error("connection: handleServerRequest:",
				"error", err, "connection", nc.id,
			)
			panic(err)
		}
	}
	if !nc.closed.Swap(true) {
		close(nc.outChan)
	}
	slog.Info("connection: handleServerRequest: finished", "connection", nc.id)
}

// handleInformInit is called when the client sends an InformInit message
// to the server, to start a new stream
func (nc *Connection) handleInformInit(msg *service.ServerInformInitRequest) {

	settings := settings.From(msg.GetSettings())

	streamId := msg.GetXInfo().GetStreamId()
	nc.stream = NewStream(settings, nc)
	nc.stream.Start()

	if err := streamMux.AddStream(streamId, nc.stream); err != nil {
		slog.Error("connection: handleInformInit: error adding stream",
			"error", err, "stream", streamId, "connection", nc.id,
		)
		// TODO: should we Close the stream?
		return
	}
	slog.Debug("connection: handleInformInit: stream created",
		"stream", streamId, "connection", nc.id,
	)

}

// handleInformStart is called when the client sends an InformStart message
// TODO: probably can remove this, we should be able to update the settings
// using the regular InformRecord messages
func (nc *Connection) handleInformStart(msg *service.ServerInformStartRequest) {
	// todo: if we keep this and end up updating the settings here
	//       we should update the stream logger to use the new settings as well
	nc.stream.settings = settings.From(msg.GetSettings())

	// update sentry tags
	// add attrs from settings:
	nc.stream.logger.SetTags(observability.Tags{
		"run_url": nc.stream.settings.GetRunURL(),
		"entity":  nc.stream.settings.GetEntity(),
	})
	// TODO: remove this once we have a better observability setup
	nc.stream.logger.CaptureInfo("core", nil)

	slog.Debug("connection: handleInformStart: stream started",
		"stream", msg.GetXInfo().GetStreamId(), "connection", nc.id,
	)
}

// handleInformAttach is called when the client sends an InformAttach message
// to the server, to attach to an existing stream.
// this is used for attaching to a stream that was previously started
// hence multiple clients can attach to the same stream
func (nc *Connection) handleInformAttach(msg *service.ServerInformAttachRequest) {
	streamId := msg.GetXInfo().GetStreamId()
	var err error
	nc.stream, err = streamMux.GetStream(streamId)
	if err != nil {
		slog.Error("connection: handleInformAttach: stream not found",
			"stream", streamId, "connection", nc.id,
		)
		return
	}

	nc.stream.AddResponders(ResponderEntry{nc, nc.id})
	// TODO: we should redo this attach logic, so that the stream handles
	//       the attach logic
	nc.Respond(
		&service.ServerResponse{
			ServerResponseType: &service.ServerResponse_InformAttachResponse{
				InformAttachResponse: &service.ServerInformAttachResponse{
					XInfo:    msg.GetXInfo(),
					Settings: nc.stream.settings.Proto,
				},
			},
		})
	slog.Debug("connection: handleInformAttach: stream attached",
		"stream", streamId, "connection", nc.id,
	)
}

// handleInformRecord is called when the client sends a record message
// this is the regular communication between the client and the server
// for a specific stream, the messages are part of the regular execution
// and are not control messages like the other Inform* messages
func (nc *Connection) handleInformRecord(msg *service.Record) {

	streamId := msg.GetXInfo().GetStreamId()

	if nc.stream == nil {
		slog.Error("handleInformRecord: stream not found",
			"stream", streamId, "connection", nc.id,
		)
		return
	}

	// add connection id to control message
	// so that the stream can send back a response
	// to the correct connection
	if msg.Control == nil {
		msg.Control = &service.Control{}
	}
	msg.Control.ConnectionId = nc.id
	nc.stream.HandleRecord(msg)
	slog.Debug("connection: handleInformRecord: record handled",
		"message", msg, "stream", streamId, "connection", nc.id,
	)
}

// handleInformFinish is called when the client sends a finish message
// this should happen when the client want to close a specific stream
func (nc *Connection) handleInformFinish(
	msg *service.ServerInformFinishRequest,
) {
	streamId := msg.GetXInfo().GetStreamId()
	stream, err := streamMux.RemoveStream(streamId)
	if err != nil {
		slog.Error("connection: handleInformFinish:",
			"error", err, "stream", streamId, "connection", nc.id,
		)
		return
	}
	stream.Close()
	slog.Debug("connection: handleInformFinish: stream finished",
		"stream", streamId, "connection", nc.id,
	)
}

// handleInformTeardown is called when the client sends a teardown message
// this should happen when the client is shutting down and wants to close
// all streams
func (nc *Connection) handleInformTeardown(
	teardown *service.ServerInformTeardownRequest,
) {
	// cancel the context to signal the server to shutdown
	// this will trigger all the connections to close
	nc.cancel()
	streamMux.FinishAndCloseAllStreams(teardown.ExitCode)
	slog.Debug("connection: handleInformTeardown: teardown",
		"exit_code", teardown.ExitCode, "connection", nc.id,
	)
}
