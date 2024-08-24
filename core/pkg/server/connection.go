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

	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/observability"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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

	// commit is the W&B Git commit hash
	commit string

	// id is the unique id for the connection
	id string

	// inChan is the channel for incoming messages
	inChan chan *spb.ServerRequest

	// outChan is the channel for outgoing messages
	outChan chan *spb.ServerResponse

	// stream is the stream for the connection, each connection has a single stream
	// however, a stream can have multiple connections
	stream *Stream

	// closed indicates if the outChan is closed
	closed *atomic.Bool

	// sentryClient is the client used to report errors to sentry.io
	sentryClient *sentry_ext.Client
}

// NewConnection creates a new connection
func NewConnection(
	ctx context.Context,
	cancel context.CancelFunc,
	conn net.Conn,
	sentryClient *sentry_ext.Client,
	commit string,
) *Connection {

	nc := &Connection{
		ctx:          ctx,
		cancel:       cancel,
		conn:         conn,
		commit:       commit,
		id:           conn.RemoteAddr().String(), // TODO: check if this is properly unique
		inChan:       make(chan *spb.ServerRequest, BufferSize),
		outChan:      make(chan *spb.ServerResponse, BufferSize),
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

func (nc *Connection) Respond(resp *spb.ServerResponse) {
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
	scanner.Buffer(make([]byte, messageSize), maxMessageSize)
	scanner.Split(ScanWBRecords)

	for scanner.Scan() {
		msg := &spb.ServerRequest{}
		if err := proto.Unmarshal(scanner.Bytes(), msg); err != nil {
			slog.Error(
				"connection: unmarshalling error",
				"error", err,
				"id", nc.id)
		} else {
			nc.inChan <- msg
		}
	}

	close(nc.inChan)

	if scanner.Err() != nil {
		switch {
		case errors.Is(scanner.Err(), net.ErrClosed):
			// All good! The connection closed normally.

		default:
			// This can happen if:
			//
			// A) The client process dies
			// B) The input is corrupted
			// C) The client process exits before finishing socket operations
			//
			// Case (A) is an expected failure mode. Case (B) should be
			// extremely rare or the result of a bug.
			//
			// Case (C) is subtle and is unavoidable by design. Unfortunately,
			// data may be lost. This happens when a child process started
			// using Python's multiprocessing exits without any completion
			// signal (e.g. run.finish()). `atexit` hooks do not run in
			// multiprocessing, so there's no way to wait for sockets to
			// flush.

			slog.Error(
				"connection: fatal error reading connection",
				"error", scanner.Err(),
				"id", nc.id,
			)
		}
	}
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
		case *spb.ServerRequest_InformInit:
			nc.handleInformInit(x.InformInit)
		case *spb.ServerRequest_InformStart:
			nc.handleInformStart(x.InformStart)
		case *spb.ServerRequest_InformAttach:
			nc.handleInformAttach(x.InformAttach)
		case *spb.ServerRequest_RecordPublish:
			nc.handleInformRecord(x.RecordPublish)
		case *spb.ServerRequest_RecordCommunicate:
			nc.handleInformRecord(x.RecordCommunicate)
		case *spb.ServerRequest_InformFinish:
			nc.handleInformFinish(x.InformFinish)
		case *spb.ServerRequest_InformTeardown:
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
func (nc *Connection) handleInformInit(msg *spb.ServerInformInitRequest) {
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

	nc.stream = NewStream(nc.commit, settings, nc.sentryClient)
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
func (nc *Connection) handleInformStart(msg *spb.ServerInformStartRequest) {
	// todo: if we keep this and end up updating the settings here
	//       we should update the stream logger to use the new settings as well
	nc.stream.settings = settings.From(msg.GetSettings())

	// update sentry tags
	// add attrs from settings:
	nc.stream.logger.SetTags(observability.Tags{
		"run_url": nc.stream.settings.GetRunURL(),
	})
	// TODO: remove this once we have a better observability setup
	nc.stream.logger.CaptureInfo("wandb-core", nil)
}

// handleInformAttach is called when the client sends an InformAttach message
// to the server, to attach to an existing stream.
// this is used for attaching to a stream that was previously started
// hence multiple clients can attach to the same stream
func (nc *Connection) handleInformAttach(msg *spb.ServerInformAttachRequest) {
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
		resp := &spb.ServerResponse{
			ServerResponseType: &spb.ServerResponse_InformAttachResponse{
				InformAttachResponse: &spb.ServerInformAttachResponse{
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
func (nc *Connection) handleInformRecord(msg *spb.Record) {
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
			msg.Control = &spb.Control{ConnectionId: nc.id}
		}
		nc.stream.HandleRecord(msg)
	}
}

// handleInformFinish is called when the client sends a finish message
// this should happen when the client want to close a specific stream
func (nc *Connection) handleInformFinish(msg *spb.ServerInformFinishRequest) {
	streamId := msg.XInfo.StreamId
	slog.Info("handle finish received", "streamId", streamId, "id", nc.id)
	if stream, err := streamMux.RemoveStream(streamId); err != nil {
		slog.Error("handleInformFinish:", "err", err, "streamId", streamId, "id", nc.id)
	} else {
		stream.Close()
	}
}

// handleInformTeardown is used by the client to shut down the entire server.
func (nc *Connection) handleInformTeardown(teardown *spb.ServerInformTeardownRequest) {
	slog.Info("connection: teardown", "id", nc.id)

	// Cancelling the context allows the server and all connections to stop.
	nc.cancel()

	// Wait for all streams to complete.
	streamMux.FinishAndCloseAllStreams(teardown.ExitCode)
}
