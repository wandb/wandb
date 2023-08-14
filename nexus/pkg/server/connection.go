package server

import (
	"bufio"
	"context"
	"encoding/binary"
	"fmt"
	"net"
	"net/url"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/auth"
	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

const (
	messageSize    = 1024 * 1024      // 1MB message size
	maxMessageSize = 64 * 1024 * 1024 // 64MB max message size
)

// Connection is the connection for a stream.
// It is a wrapper around the underlying connection
// It handles the incoming messages from the client
// and passes them to the stream
type Connection struct {
	// ctx is the context for the connection
	ctx context.Context

	// conn is the underlying connection
	conn net.Conn

	// id is the unique id for the connection
	id string

	// inChan is the channel for incoming messages
	inChan chan *service.ServerRequest

	// outChan is the channel for outgoing messages
	outChan chan *service.ServerResponse

	// teardownChan is the channel for signaling teardown
	teardownChan chan struct{}

	// stream is the stream for the connection, each connection has a single stream
	// however, a stream can have multiple connections
	stream *Stream
}

// NewConnection creates a new connection
func NewConnection(
	ctx context.Context,
	conn net.Conn,
	teardown chan struct{},
) *Connection {

	nc := &Connection{
		ctx:          ctx,
		conn:         conn,
		id:           conn.RemoteAddr().String(), // TODO: check if this is properly unique
		inChan:       make(chan *service.ServerRequest, BufferSize),
		outChan:      make(chan *service.ServerResponse, BufferSize),
		teardownChan: teardown, //TODO: should we trigger teardown from a connection?
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
	scanner.Split(tokenizer.split)
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
	close(nc.outChan)
	slog.Debug("finished handleServerRequest", "id", nc.id)
}

// handleInformInit is called when the client sends an InformInit message
// to the server, to start a new stream
func (nc *Connection) handleInformInit(msg *service.ServerInformInitRequest) {
	settings := msg.GetSettings()

	func(s *service.Settings) {
		if s.GetApiKey().GetValue() != "" {
			return
		}
		baseUrl := s.GetBaseUrl().GetValue()
		u, err := url.Parse(baseUrl)
		if err != nil {
			slog.Error("error parsing url", "err", err, "url", baseUrl)
			panic(err)
		}
		host := u.Hostname()
		_, password, err := auth.GetNetrcLogin(host)
		if err != nil {
			slog.Error("error getting password from netrc", "err", err, "id", nc.id)
			panic(err)
		}
		s.ApiKey = &wrapperspb.StringValue{Value: password}
	}(settings) // TODO: this is a hack, we should not be modifying the settings

	streamId := msg.GetXInfo().GetStreamId()
	slog.Info("connection init received", "streamId", streamId, "id", nc.id)
	// TODO: redo this function, to only init the stream and have the stream
	//       handle the rest of the startup
	nc.stream = NewStream(nc.ctx, settings, streamId)
	nc.stream.AddResponders(ResponderEntry{nc, nc.id})

	if err := streamMux.AddStream(streamId, nc.stream); err != nil {
		slog.Error("connection init failed, stream already exists", "streamId", streamId, "id", nc.id)
		// TODO: should we Close the stream?
		return
	}
}

// handleInformStart is called when the client sends an InformStart message
// TODO: probably can remove this, we should be able to update the settings
// using the regular InformRecord messages
func (nc *Connection) handleInformStart(_ *service.ServerInformStartRequest) {
	// todo: if we keep this and end up updating the settings here
	//       we should update the stream logger to use the new settings as well
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
					Settings: nc.stream.settings,
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
	close(nc.teardownChan)
	streamMux.FinishAndCloseAllStreams(teardown.ExitCode)
	nc.Close()
}
