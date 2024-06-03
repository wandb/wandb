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

	"github.com/wandb/wandb/core/internal/sentry"
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

	// sentryClient is the client used to report errors to sentry.io
	sentryClient *sentry.Client
}

// NewConnection creates a new connection
func NewConnection(
	ctx context.Context,
	cancel context.CancelFunc,
	conn net.Conn,
	sentryClient *sentry.Client,
) *Connection {

	nc := &Connection{
		ctx:          ctx,
		cancel:       cancel,
		conn:         conn,
		id:           conn.RemoteAddr().String(), // TODO: check if this is properly unique
		inChan:       make(chan *service.ServerRequest, BufferSize),
		outChan:      make(chan *service.ServerResponse, BufferSize),
		closed:       &atomic.Bool{},
		sentryClient: sentryClient,
	}
	return nc
}

// HandleConnection handles the connection by reading from the connection
// and passing the messages to the stream
// and writing messages from the stream to the connection
func (nc *Connection) HandleConnection() {
	slog.Info("created new connection", "id", nc.id)

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

	slog.Info("connection closed", "id", nc.id)
}

// Close closes the connection
func (nc *Connection) Close() {
	slog.Debug("closing connection", "id", nc.id)
	if err := nc.conn.Close(); err != nil {
		slog.Error("error closing connection", "err", err, "id", nc.id)
	}
	slog.Info("closed connection", "id", nc.id)
}

func (nc *Connection) Respond(resp *service.ServerResponse) {
	if nc.closed.Load() {
		// TODO: this is a bit of a hack, we should probably handle this better
		//       and not send responses to closed connections
		slog.Error("connection is closed", "id", nc.id)
		return
	}
	nc.outChan <- resp
}

// readConnection reads the streaming connection
// it reads raw bytes from the connection and parses them into protobuf messages
// it passes the messages to the inChan to be handled by handleServerRequest
// it closes the inChan when the connection is closed
func (nc *Connection) readConnection() {
	scanner := bufio.NewScanner(nc.conn)
	buf := make([]byte, messageSize)
	scanner.Buffer(buf, maxMessageSize)
	tokenizer := &Tokenizer{}
	scanner.Split(tokenizer.Split)
	for scanner.Scan() {
		msg := &service.ServerRequest{}
		if err := proto.Unmarshal(scanner.Bytes(), msg); err != nil {
			slog.Error(
				"unmarshalling error",
				"err", err,
				"conn", nc.conn.RemoteAddr())
		} else {
			nc.inChan <- msg
		}
	}
	if scanner.Err() != nil && !errors.Is(scanner.Err(), net.ErrClosed) {
		panic(scanner.Err())
	}
	close(nc.inChan)
}

// handleServerRequest handles outgoing messages from the server
// to the client, it writes the messages to the connection
// the client is responsible for reading and parsing the messages
func (nc *Connection) handleServerResponse() {
	slog.Debug("starting handleServerResponse", "id", nc.id)
	for msg := range nc.outChan {
		out, err := proto.Marshal(msg)
		if err != nil {
			slog.Error("error marshalling msg", "err", err, "id", nc.id)
			return
		}

		writer := bufio.NewWriter(nc.conn)
		header := Header{Magic: byte('W'), DataLength: uint32(len(out))}
		if err = binary.Write(writer, binary.LittleEndian, &header); err != nil {
			slog.Error("error writing header", "err", err, "id", nc.id)
			return
		}
		if _, err = writer.Write(out); err != nil {
			slog.Error("error writing msg", "err", err, "id", nc.id)
			return
		}

		if err = writer.Flush(); err != nil {
			slog.Error("error flushing writer", "err", err, "id", nc.id)
			return
		}
	}
	slog.Debug("finished handleServerResponse", "id", nc.id)
}

// handleServerRequest handles incoming messages from the client
// to the server, it passes the messages to the stream
func (nc *Connection) handleServerRequest() {
	slog.Debug("starting handleServerRequest", "id", nc.id)
	for msg := range nc.inChan {
		slog.Debug("handling server request", "msg", msg, "id", nc.id)
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
			slog.Error("ServerRequestType is nil", "id", nc.id)
			panic("ServerRequestType is nil")
		default:
			slog.Error("ServerRequestType is unknown", "type", x, "id", nc.id)
			panic(fmt.Sprintf("ServerRequestType is unknown, %T", x))
		}
	}
	if !nc.closed.Swap(true) {
		close(nc.outChan)
	}
	slog.Debug("finished handleServerRequest", "id", nc.id)
}

// handleInformInit is called when the client sends an InformInit message
// to the server, to start a new stream
func (nc *Connection) handleInformInit(msg *service.ServerInformInitRequest) {
	settings := settings.From(msg.GetSettings())

	err := settings.EnsureAPIKey()
	if err != nil {
		slog.Error(
			"connection: couldn't get API key",
			"err", err,
			"id", nc.id,
		)
		panic(err)
	}

	streamId := msg.GetXInfo().GetStreamId()
	slog.Info("connection init received", "streamId", streamId, "id", nc.id)

	nc.stream = NewStream(settings, streamId, nc.sentryClient)
	nc.stream.AddResponders(ResponderEntry{nc, nc.id})
	nc.stream.Start()
	slog.Info("connection init completed", "streamId", streamId, "id", nc.id)

	if err := streamMux.AddStream(streamId, nc.stream); err != nil {
		slog.Error("connection init failed, stream already exists", "streamId", streamId, "id", nc.id)
		// TODO: should we Close the stream?
		return
	}
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
	nc.stream.logger.CaptureInfo("wandb-core", nil)
}

// handleInformAttach is called when the client sends an InformAttach message
// to the server, to attach to an existing stream.
// this is used for attaching to a stream that was previously started
// hence multiple clients can attach to the same stream
func (nc *Connection) handleInformAttach(msg *service.ServerInformAttachRequest) {
	streamId := msg.GetXInfo().GetStreamId()
	slog.Debug("handle record received", "streamId", streamId, "id", nc.id)
	var err error
	nc.stream, err = streamMux.GetStream(streamId)
	if err != nil {
		slog.Error("handleInformAttach: stream not found", "streamId", streamId, "id", nc.id)
	} else {
		nc.stream.AddResponders(ResponderEntry{nc, nc.id})
		// TODO: we should redo this attach logic, so that the stream handles
		//       the attach logic
		resp := &service.ServerResponse{
			ServerResponseType: &service.ServerResponse_InformAttachResponse{
				InformAttachResponse: &service.ServerInformAttachResponse{
					XInfo:    msg.XInfo,
					Settings: nc.stream.settings.Proto,
				},
			},
		}
		nc.Respond(resp)
	}
}

// handleInformRecord is called when the client sends a record message
// this is the regular communication between the client and the server
// for a specific stream, the messages are part of the regular execution
// and are not control messages like the other Inform* messages
func (nc *Connection) handleInformRecord(msg *service.Record) {
	streamId := msg.GetXInfo().GetStreamId()
	slog.Debug("handle record received", "streamId", streamId, "id", nc.id)
	if nc.stream == nil {
		slog.Error("handleInformRecord: stream not found", "streamId", streamId, "id", nc.id)
	} else {
		// add connection id to control message
		// so that the stream can send back a response
		// to the correct connection
		if msg.Control != nil {
			msg.Control.ConnectionId = nc.id
		} else {
			msg.Control = &service.Control{ConnectionId: nc.id}
		}
		nc.stream.HandleRecord(msg)
	}
}

// handleInformFinish is called when the client sends a finish message
// this should happen when the client want to close a specific stream
func (nc *Connection) handleInformFinish(msg *service.ServerInformFinishRequest) {
	streamId := msg.XInfo.StreamId
	slog.Info("handle finish received", "streamId", streamId, "id", nc.id)
	if stream, err := streamMux.RemoveStream(streamId); err != nil {
		slog.Error("handleInformFinish:", "err", err, "streamId", streamId, "id", nc.id)
	} else {
		stream.Close()
	}
}

// handleInformTeardown is called when the client sends a teardown message
// this should happen when the client is shutting down and wants to close
// all streams
func (nc *Connection) handleInformTeardown(teardown *service.ServerInformTeardownRequest) {
	slog.Debug("handle teardown received", "id", nc.id)
	// cancel the context to signal the server to shutdown
	// this will trigger all the connections to close
	nc.cancel()
	streamMux.FinishAndCloseAllStreams(teardown.ExitCode)
}
