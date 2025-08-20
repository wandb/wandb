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

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

const (
	messageSize    = 1024 * 1024            // 1MB message size
	maxMessageSize = 2 * 1024 * 1024 * 1024 // 2GB max message size
)

type ConnectionParams struct {
	StreamMux          *stream.StreamMux
	GPUResourceManager *monitor.GPUResourceManager

	ID string

	Conn         net.Conn
	SentryClient *sentry_ext.Client
	Commit       string
	LoggerPath   string
	LogLevel     slog.Level
}

// Connection represents a client-server connection in the context of a streaming session.
//
// It acts as a wrapper around the underlying network connection and handles the flow of
// messages between the client and the server. This includes managing incoming requests
// and outgoing responses, maintaining the state of the connection, and providing
// error reporting mechanisms.
type Connection struct {
	// connLifetimeCtx is cancelled when the connection should be closed.
	connLifetimeCtx context.Context

	// stopServer signals the server to shut down, which also closes all
	// connections.
	stopServer context.CancelFunc

	// The underlying network connection. This represents the raw TCP connection
	// layer that facilitates communication between the client and the server.
	conn net.Conn

	// A map that associates stream IDs with active streams (or runs). This helps
	// track the streams associated with this connection.
	streamMux *stream.StreamMux

	// gpuResourceManager is used by streams for system GPU metrics.
	gpuResourceManager *monitor.GPUResourceManager

	// id is the unique id for the connection
	id string

	// inChan is the channel for incoming messages
	inChan chan *spb.ServerRequest

	// outChan is the channel for outgoing messages
	outChan chan *spb.ServerResponse

	// An atomic flag indicating whether the `outChan` has been closed, ensuring
	// thread-safe checking and updating of the connection’s closure state.
	closed *atomic.Bool

	// The current W&B Git commit hash, identifying the specific version of the binary.
	commit string

	// sentryClient is the sentry client
	sentryClient *sentry_ext.Client

	// loggerPath is the path to the logger
	loggerPath string

	// logLevel is the log level
	logLevel slog.Level
}

func NewConnection(
	serverLifetimeCtx context.Context,
	stopServer context.CancelFunc,
	params ConnectionParams,
) *Connection {
	return &Connection{
		connLifetimeCtx:    serverLifetimeCtx,
		stopServer:         stopServer,
		streamMux:          params.StreamMux,
		gpuResourceManager: params.GPUResourceManager,
		conn:               params.Conn,
		commit:             params.Commit,
		id:                 params.ID,
		inChan:             make(chan *spb.ServerRequest, BufferSize),
		outChan:            make(chan *spb.ServerResponse, BufferSize),
		closed:             &atomic.Bool{},
		sentryClient:       params.SentryClient,
		loggerPath:         params.LoggerPath,
		logLevel:           params.LogLevel,
	}
}

// ManageConnectionData processes the connection until the server shuts down,
// the peer closes the connection, or an error is encountered.
//
// After this exits, any messages that were received without error have been
// processed and the underlying connection has been closed.
func (nc *Connection) ManageConnectionData() {
	slog.Info("connection: ManageConnectionData: new connection created", "id", nc.id)

	wg := sync.WaitGroup{}

	wg.Add(1)
	go func() {
		defer wg.Done()
		nc.processIncomingData()
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		nc.handleIncomingRequests()
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		nc.processOutgoingData()
	}()

	<-nc.connLifetimeCtx.Done()

	// Close the underlying connection, which allows the above goroutines
	// to eventually exit if the connection was not already closed.
	//
	// From this point, the peer will receive errors when trying to write
	// to or read from the connection.
	nc.Close()

	wg.Wait()

	slog.Info("connection: ManageConnectionData: connection closed", "id", nc.id)
}

// processOutgoingData processes and sends outgoing messages from the server to the client.
//
// It reads protobuf messages from the `outChan`, serializes them, and writes the serialized
// data to the network connection. The client is responsible for reading and parsing the messages.
// If any error occurs during serialization or writing, the function logs the error and terminates
// early to prevent further message processing.
func (nc *Connection) processOutgoingData() {
	slog.Debug("processOutgoingData: started", "id", nc.id)

	for msg := range nc.outChan {
		// Marshal the message to protobuf format
		out, err := proto.Marshal(msg)
		if err != nil {
			slog.Error("processOutgoingData: marshalling error", "error", err, "id", nc.id)
			return
		}

		writer := bufio.NewWriter(nc.conn)
		// Write header with message length
		header := Header{
			Magic:      byte('W'),
			DataLength: uint32(len(out)),
		}
		if err = binary.Write(writer, binary.LittleEndian, &header); err != nil {
			slog.Error("processOutgoingData: header writing error", "error", err, "id", nc.id)
			return
		}

		// Write the message body
		if _, err = writer.Write(out); err != nil {
			slog.Error("processOutgoingData: message writing error", "error", err, "id", nc.id)
			return
		}

		// Flush the writer buffer to ensure data is sent
		if err = writer.Flush(); err != nil {
			slog.Error("processOutgoingData: flush error", "error", err, "id", nc.id)
			return
		}
	}

	slog.Debug("processOutgoingData: finished", "id", nc.id)
}

// processIncomingData reads and processes messages from a network connection.
//
// This function listens for incoming data on the network connection, parses it
// into protobuf messages, and sends those messages to the `inChan` channel for
// further handling. When the connection closes, the `inChan` channel is also
// closed to signal that no more data will be received.
//
// If an error occurs during message parsing or reading from the connection,
// it will be logged with relevant details. Expected failure scenarios, such as
// client disconnections or process terminations, are handled gracefully.
//
// The function ensures that data is processed as efficiently as possible and
// provides error logging for unexpected situations that may arise during
// communication.
func (nc *Connection) processIncomingData() {

	scanner := bufio.NewScanner(nc.conn)
	// TODO: on 32-bit systems, we need to use a smaller buffer size
	scanner.Buffer(make([]byte, messageSize), maxMessageSize)
	scanner.Split(ScanWBRecords)

	for scanner.Scan() {
		msg := &spb.ServerRequest{}
		if err := proto.Unmarshal(scanner.Bytes(), msg); err != nil {
			dataLen := len(scanner.Bytes())
			dataTrunc := scanner.Bytes()
			if len(dataTrunc) > 1<<10 {
				dataTrunc = dataTrunc[:1<<10]
			}

			slog.Error(
				"connection: unmarshalling error, breaking connection",
				"error", err,
				"id", nc.id,
				"token_len", dataLen,
				"token_1kb", dataTrunc,
			)

			// Stop the server because a client is misbehaving, and it is no
			// longer guaranteed that the server will receive a teardown
			// request.
			//
			// The failsafe mechanism that shuts down the server if the parent
			// process exits is not reliable here, as the client may be waiting
			// for the server to shut down before exiting.
			nc.stopServer()
			break
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

// handleIncomingRequests handles incoming messages from the client.
//
// This function ensures proper message routing based on the message type. If an
// unknown or invalid message type is encountered, the function logs an error and
// halts processing.
//
// Once all messages are processed, it safely closes the outgoing message channel.
func (nc *Connection) handleIncomingRequests() {
	slog.Debug("handleIncomingRequests: started", "id", nc.id)

	for msg := range nc.inChan {
		slog.Debug("handleIncomingRequests: processing message", "msg", msg, "id", nc.id)

		switch x := msg.ServerRequestType.(type) {
		case *spb.ServerRequest_Authenticate:
			nc.handleAuthenticate(x.Authenticate)
		case *spb.ServerRequest_InformInit:
			nc.handleInformInit(x.InformInit)
		case *spb.ServerRequest_InformStart:
			nc.handleInformStart(x.InformStart)
		case *spb.ServerRequest_InformAttach:
			nc.handleInformAttach(msg.RequestId, x.InformAttach)
		case *spb.ServerRequest_RecordPublish:
			nc.handleInformRecord(x.RecordPublish)
		case *spb.ServerRequest_RecordCommunicate:
			nc.handleInformRecord(x.RecordCommunicate)
		case *spb.ServerRequest_InformFinish:
			nc.handleInformFinish(x.InformFinish)
		case *spb.ServerRequest_InformTeardown:
			nc.handleInformTeardown(x.InformTeardown)
		case nil:
			slog.Error("handleIncomingRequests: ServerRequestType is nil", "id", nc.id)
			panic("ServerRequestType is nil")
		default:
			slog.Error("handleIncomingRequests: unknown ServerRequestType", "type", x, "id", nc.id)
			panic(fmt.Sprintf("Unknown ServerRequestType: %T", x))
		}
	}

	// Ensure outChan is closed if connection isn't already marked as closed
	if !nc.closed.Swap(true) {
		close(nc.outChan)
	}

	slog.Debug("handleIncomingRequests: finished", "id", nc.id)
}

// handleInformInit handles the initialization of a new stream by the client.
//
// This function is invoked when the server receives an `InformInit` message
// from the client. It creates a new stream, associates it with the connection.
// Also starts the stream and adds the connection as a responder to the stream.
func (nc *Connection) handleInformInit(msg *spb.ServerInformInitRequest) {
	settings := settings.From(msg.GetSettings())

	streamId := msg.GetXInfo().GetStreamId()
	slog.Info("handleInformInit: received", "streamId", streamId, "id", nc.id)

	// if we are in offline mode, we don't want to send any data to sentry
	var sentryClient *sentry_ext.Client
	if settings.IsOffline() {
		sentryClient = sentry_ext.New(sentry_ext.Params{Disabled: true})
	} else {
		sentryClient = nc.sentryClient
	}

	strm := stream.InjectStream(
		stream.GitCommitHash(nc.commit),
		nc.gpuResourceManager,
		stream.DebugCorePath(nc.loggerPath),
		nc.logLevel,
		nc.sentryClient,
		settings,
	)
	strm.AddResponders(stream.ResponderEntry{Responder: nc, ID: nc.id})
	strm.Start()
	slog.Info("handleInformInit: stream started", "streamId", streamId, "id", nc.id)

	// TODO: remove this once we have a better observability setup
	sentryClient.CaptureMessage("wandb-core", nil)

	if err := nc.streamMux.AddStream(streamId, strm); err != nil {
		slog.Error("handleInformInit: error adding stream", "err", err, "streamId", streamId, "id", nc.id)
		// TODO: should we Close the stream?
		return
	}
}

// handleInformStart handles the start message from the client.
//
// This function is invoked when the server receives an `InformStart` message
// from the client. It updates the stream settings with the provided settings
// from the client.
//
// TODO: should probably remove this message and use a different mechanism
// to update stream settings
func (nc *Connection) handleInformStart(msg *spb.ServerInformStartRequest) {
	slog.Debug("handleInformStart: received", "id", nc.id)

	strm, err := nc.streamMux.GetStream(msg.GetXInfo().GetStreamId())
	if err != nil {
		slog.Error(
			"handleInformStart: error getting stream",
			"err", err, "id", nc.id)
	} else {
		strm.UpdateSettings(settings.From(msg.GetSettings()))
		strm.UpdateRunURLTag()
	}
}

// handleInformAttach handles the new connection attaching to an existing stream.
//
// This function is invoked when the server receives an `InformAttach` message
// from the client. It attaches a new client connection to an existing stream
// and sends an update to the client with the stream settings. The client can
// then use these settings to update its local state.
func (nc *Connection) handleInformAttach(
	requestID string,
	msg *spb.ServerInformAttachRequest,
) {
	streamId := msg.GetXInfo().GetStreamId()
	slog.Debug("handle record received", "streamId", streamId, "id", nc.id)
	strm, err := nc.streamMux.GetStream(streamId)
	if err != nil {
		slog.Error(
			"handleInformAttach: error getting stream",
			"err", err, "id", nc.id)
	} else {
		strm.AddResponders(stream.ResponderEntry{Responder: nc, ID: nc.id})
		// TODO: we should redo this attach logic, so that the stream handles
		//       the attach logic
		resp := &spb.ServerResponse{
			RequestId: requestID,
			ServerResponseType: &spb.ServerResponse_InformAttachResponse{
				InformAttachResponse: &spb.ServerInformAttachResponse{
					XInfo:    msg.XInfo,
					Settings: strm.GetSettings().Proto,
				},
			},
		}
		nc.Respond(resp)
	}
}

// handleAuthenticate processes client authentication messages.
//
// It validates client credentials and responds with the default entity
// associated with the provided API key. This lightweight authentication
// method avoids the overhead of starting a new stream while still
// leveraging wandb-core's features.
//
// An alternative approach would be implementing a GraphQL Viewer query
// on the client side for each supported language.
//
// Note: This function will be deprecated once the Public API workflow
// in wandb-core is implemented.
func (nc *Connection) handleAuthenticate(msg *spb.ServerAuthenticateRequest) {
	slog.Debug("handleAuthenticate: received", "id", nc.id)

	s := settings.From(&spb.Settings{
		ApiKey:  &wrapperspb.StringValue{Value: msg.ApiKey},
		BaseUrl: &wrapperspb.StringValue{Value: msg.BaseUrl},
	})
	backend := stream.NewBackend(observability.NewNoOpLogger(), s) // TODO: use a real logger
	graphqlClient := stream.NewGraphQLClient(backend, s, &observability.Peeker{}, "" /*clientId*/)

	data, err := gql.Viewer(context.Background(), graphqlClient)
	if err != nil || data == nil || data.GetViewer() == nil || data.GetViewer().GetEntity() == nil {
		nc.Respond(&spb.ServerResponse{
			ServerResponseType: &spb.ServerResponse_AuthenticateResponse{
				AuthenticateResponse: &spb.ServerAuthenticateResponse{
					ErrorStatus: "Invalid credentials",
					XInfo:       msg.XInfo,
				},
			},
		})
		return
	}

	nc.Respond(&spb.ServerResponse{
		ServerResponseType: &spb.ServerResponse_AuthenticateResponse{
			AuthenticateResponse: &spb.ServerAuthenticateResponse{
				DefaultEntity: *data.GetViewer().GetEntity(),
				XInfo:         msg.XInfo,
			},
		},
	})
}

// handleInformRecord processes a regular record message from the client.
//
// This function is called when the client sends a record message as part of the
// ongoing communication for a specific stream. Record messages are distinct from
// control messages like Inform* messages and are part of the normal data exchange
// between the client and server.
//
// The function ensures that the message is sent to the correct stream for processing.
// It also adds the connection ID to the control message so that the stream can send
// a response back to the correct connection.
func (nc *Connection) handleInformRecord(msg *spb.Record) {
	streamId := msg.GetXInfo().GetStreamId()

	slog.Debug("handleInformRecord: record received", "streamId", streamId, "id", nc.id)

	strm, err := nc.streamMux.GetStream(streamId)
	if err != nil {
		slog.Error(
			"handleInformRecord: error getting stream",
			"err", err, "id", nc.id)
		return
	}

	// Add the connection ID to the control message to ensure the response is
	// sent to the correct connection
	if msg.Control != nil {
		msg.Control.ConnectionId = nc.id
	} else {
		msg.Control = &spb.Control{ConnectionId: nc.id}
	}

	// Delegate the handling of the record to the stream
	strm.HandleRecord(msg)
}

// handleInformFinish processes a finish message from the client.
//
// This function is called when the client sends a finish message, indicating the
// intent to close a specific stream. It removes the stream associated with the
// given stream ID from the stream multiplexer and safely closes the stream.
func (nc *Connection) handleInformFinish(msg *spb.ServerInformFinishRequest) {
	streamId := msg.XInfo.StreamId
	slog.Info("handleInformFinish: finish message received", "streamId", streamId, "id", nc.id)

	// Attempt to remove the stream from the stream multiplexer
	strm, err := nc.streamMux.RemoveStream(streamId)
	if err != nil {
		slog.Error("handleInformFinish: error removing stream", "err", err, "streamId", streamId, "id", nc.id)
		return
	}

	// Safely close the stream
	strm.Close()
	slog.Info("handleInformFinish: stream closed", "streamId", streamId, "id", nc.id)
}

// handleInformTeardown processes a request from the client to shut down the server.
//
// This function is called when the client sends a teardown message, signaling the server
// to stop all operations. It cancels the server's context, causing all ongoing connections
// and streams to gracefully shut down. The function then waits for all active streams to
// complete and close with the provided exit code.
func (nc *Connection) handleInformTeardown(teardown *spb.ServerInformTeardownRequest) {
	slog.Info("handleInformTeardown: server teardown initiated", "id", nc.id)
	nc.stopServer()

	// Close all streams and wait for completion, passing the provided exit code.
	nc.streamMux.FinishAndCloseAllStreams(teardown.ExitCode)

	slog.Info("handleInformTeardown: server shutdown complete", "id", nc.id)
}

// Close closes the underlying TCP connection.
//
// Any blocked reads or writes will return an error.
func (nc *Connection) Close() {
	slog.Info("connection: closing", "id", nc.id)

	if err := nc.conn.Close(); err != nil {
		slog.Error("connection: error closing", "error", err, "id", nc.id)
	} else {
		slog.Info("connection: closed successfully", "id", nc.id)
	}
}

// Respond impplements the Responder interface to send a response to the client.
//
// This is used to send a response to the outgoing message channel for the connection.
// The response is then processed and sent to the client by the `processOutgoingData`
// function.
func (nc *Connection) Respond(resp *spb.ServerResponse) {

	// Check if the connection has already been closed
	if nc.closed.Load() {
		// TODO: this is a bit of a hack, we should probably handle this better
		//       and not send responses to closed connections
		slog.Warn("connection: Respond: attempt to send response on closed connection", "id", nc.id)
		return
	}

	nc.outChan <- resp
}
