package connection

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/url"
	"sync"

	"github.com/wandb/wandb/core/internal/auth"
	"github.com/wandb/wandb/core/internal/lib/shared"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/server/stream"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

const (
	messageSize    = 1024 * 1024            // 1MB message size
	maxMessageSize = 2 * 1024 * 1024 * 1024 // 2GB max message size
	BufferSize     = 24
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
	inChan chan *pb.ServerRequest

	// outChan is the channel for outgoing messages
	outChan chan *pb.ServerResponse

	// teardownChan is the channel for signaling teardown
	teardownChan chan struct{}

	// stream is the stream for the connection, each connection has a single stream
	// however, a stream can have multiple connections
	stream *stream.Stream
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
		inChan:       make(chan *pb.ServerRequest, BufferSize),
		outChan:      make(chan *pb.ServerResponse, BufferSize),
		teardownChan: teardown, // TODO: should we trigger teardown from a connection?
	}
	return nc
}

// HandleConnection handles the connection by reading from the connection
// and passing the messages to the stream
// and writing messages from the stream to the connection
func (c *Connection) HandleConnection() {
	slog.Info("created new connection", "id", c.id)

	wg := sync.WaitGroup{}

	wg.Add(1)
	go func() {
		c.read()
		wg.Done()
	}()

	wg.Add(1)
	go func() {
		c.handle()
		wg.Done()
	}()

	wg.Add(1)
	go func() {
		c.write()
		wg.Done()
	}()

	// Force shutdown of connections on teardown.
	// TODO(beta): refactor the connection code so this is not needed
	// Why this is needed right now:
	//   - client might have multiple open connections to core
	//   - teardown usually is sent on a new connection
	//   - teardown closes teardownChan but we have nothing to
	//     force shutdown of other connections
	wgTeardown := sync.WaitGroup{}
	wgTeardown.Add(1)
	teardownWatcherChan := make(chan interface{})
	go func() {
		select {
		case <-c.teardownChan:
			c.Close()
			break
		case <-teardownWatcherChan:
			break
		}
		wgTeardown.Done()
	}()

	wg.Wait()
	close(teardownWatcherChan)
	wgTeardown.Wait()

	slog.Info("connection closed", "id", c.id)
}

// Close closes the connection
func (c *Connection) Close() {
	slog.Debug("closing connection", "id", c.id)
	if err := c.conn.Close(); err != nil {
		slog.Error("error closing connection", "err", err, "id", c.id)
	}
	slog.Info("closed connection", "id", c.id)
}

func (c *Connection) Respond(resp *pb.ServerResponse) {
	c.outChan <- resp
}

// read reads the streaming connection
// it reads raw bytes from the connection and parses them into protobuf messages
// it passes the messages to the inChan to be handled by handleServerRequest
// it closes the inChan when the connection is closed
func (c *Connection) read() {
	scanner := bufio.NewScanner(c.conn)
	buf := make([]byte, messageSize)
	scanner.Buffer(buf, maxMessageSize)
	tokenizer := &shared.Tokenizer{}
	scanner.Split(tokenizer.Split)
	for scanner.Scan() {
		msg := &pb.ServerRequest{}
		if err := proto.Unmarshal(scanner.Bytes(), msg); err != nil {
			slog.Error(
				"unmarshalling error",
				"err", err,
				"conn", c.conn.RemoteAddr())
		} else {
			c.inChan <- msg
		}
	}
	if scanner.Err() != nil && !errors.Is(scanner.Err(), net.ErrClosed) {
		panic(scanner.Err())
	}
	close(c.inChan)
}

// write responsible for writing to the streaming connection
// it writes raw bytes to the connection out of the protobuf messages
// it reads the messages from the outChan
func (c *Connection) write() {
	slog.Debug("starting handleServerResponse", "id", c.id)
	for msg := range c.outChan {
		bytes, err := proto.Marshal(msg)
		if err != nil {
			slog.Error("error marshalling msg", "err", err, "id", c.id)
			return
		}
		writer := bufio.NewWriter(c.conn)
		if err := shared.Write(writer, bytes); err != nil {
			slog.Error("error writing msg", "err", err, "id", c.id)
			return
		}
		if err := writer.Flush(); err != nil {
			slog.Error("error flushing writer", "err", err, "id", c.id)
			return
		}
	}
	slog.Debug("finished handleServerResponse", "id", c.id)
}

// handle handles incoming messages from the client
// to the server, it passes the messages to the stream
func (c *Connection) handle() {
	slog.Debug("starting handleServerRequest", "id", c.id)
	for msg := range c.inChan {
		slog.Debug("handling server request", "msg", msg, "id", c.id)
		switch x := msg.ServerRequestType.(type) {
		case *pb.ServerRequest_InformInit:
			c.handleInformInit(x.InformInit)
		case *pb.ServerRequest_InformStart:
			c.handleInformStart(x.InformStart)
		case *pb.ServerRequest_InformAttach:
			c.handleInformAttach(x.InformAttach)
		case *pb.ServerRequest_RecordPublish:
			c.handleInformRecord(x.RecordPublish)
		case *pb.ServerRequest_RecordCommunicate:
			c.handleInformRecord(x.RecordCommunicate)
		case *pb.ServerRequest_InformFinish:
			c.handleInformFinish(x.InformFinish)
		case *pb.ServerRequest_InformTeardown:
			c.handleInformTeardown(x.InformTeardown)
		case nil:
			slog.Error("ServerRequestType is nil", "id", c.id)
			panic("ServerRequestType is nil")
		default:
			slog.Error("ServerRequestType is unknown", "type", x, "id", c.id)
			panic(fmt.Sprintf("ServerRequestType is unknown, %T", x))
		}
	}
	close(c.outChan)
	slog.Debug("finished handleServerRequest", "id", c.id)
}

// handleInformInit is called when the client sends an InformInit message
// to the server, to start a new stream
func (c *Connection) handleInformInit(msg *pb.ServerInformInitRequest) {
	settings := msg.GetSettings()
	func(s *pb.Settings) {
		if s.GetApiKey().GetValue() != "" {
			return
		}
		if s.GetXOffline().GetValue() {
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
			slog.Error("error getting password from netrc", "err", err, "id", c.id)
			panic(err)
		}
		s.ApiKey = &wrapperspb.StringValue{Value: password}
	}(settings)

	streamId := msg.GetXInfo().GetStreamId()
	slog.Info("connection init received", "streamId", streamId, "id", c.id)
	// TODO: redo this function, to only init the stream and have the stream
	//       handle the rest of the startup
	c.stream = stream.NewStream(c.ctx, settings, streamId)
	c.stream.AddResponders(stream.ResponderEntry{Responder: c, ID: c.id})
	c.stream.Start()

	if err := stream.Mux.AddStream(streamId, c.stream); err != nil {
		slog.Error("connection init failed, stream already exists", "streamId", streamId, "id", c.id)
		// TODO: should we Close the stream?
		return
	}
}

// handleInformStart is called when the client sends an InformStart message
// TODO: probably can remove this, we should be able to update the settings
// using the regular InformRecord messages
func (c *Connection) handleInformStart(msg *pb.ServerInformStartRequest) {
	// todo: if we keep this and end up updating the settings here
	//       we should update the stream logger to use the new settings as well
	c.stream.Settings = msg.GetSettings()
	// update sentry tags
	// add attrs from settings:
	c.stream.Logger.SetTags(observability.Tags{
		"run_url": c.stream.Settings.GetRunUrl().GetValue(),
		"entity":  c.stream.Settings.GetEntity().GetValue(),
	})
	c.stream.Logger.Info("received start message on connection", "id", c.id)
}

// handleInformAttach is called when the client sends an InformAttach message
// to the server, to attach to an existing stream.
// this is used for attaching to a stream that was previously started
// hence multiple clients can attach to the same stream
func (c *Connection) handleInformAttach(msg *pb.ServerInformAttachRequest) {
	streamId := msg.GetXInfo().GetStreamId()
	slog.Debug("handle record received", "streamId", streamId, "id", c.id)
	var err error
	c.stream, err = stream.Mux.GetStream(streamId)
	if err != nil {
		slog.Error("handleInformAttach: stream not found", "streamId", streamId, "id", c.id)
	} else {
		c.stream.Logger.Info("handleInformAttach: stream found", "streamId", streamId, "id", c.id)
		c.stream.AddResponders(stream.ResponderEntry{Responder: c, ID: c.id})
		// TODO: we should redo this attach logic, so that the stream handles
		//       the attach logic
		resp := &pb.ServerResponse{
			ServerResponseType: &pb.ServerResponse_InformAttachResponse{
				InformAttachResponse: &pb.ServerInformAttachResponse{
					XInfo:    msg.XInfo,
					Settings: c.stream.Settings,
				},
			},
		}
		c.Respond(resp)
	}
}

// handleInformRecord is called when the client sends a record message
// this is the regular communication between the client and the server
// for a specific stream, the messages are part of the regular execution
// and are not control messages like the other Inform* messages
func (c *Connection) handleInformRecord(msg *pb.Record) {
	streamId := msg.GetXInfo().GetStreamId()
	slog.Debug("handle record received", "streamId", streamId, "id", c.id)
	if c.stream == nil {
		slog.Error("handleInformRecord: stream not found", "streamId", streamId, "id", c.id)
	} else {
		// add connection id to control message
		// so that the stream can send back a response
		// to the correct connection
		if msg.Control != nil {
			msg.Control.ConnectionId = c.id
		} else {
			msg.Control = &pb.Control{ConnectionId: c.id}
		}
		c.stream.HandleRecord(msg)
	}
}

// handleInformFinish is called when the client sends a finish message
// this should happen when the client want to close a specific stream
func (c *Connection) handleInformFinish(msg *pb.ServerInformFinishRequest) {
	streamId := msg.XInfo.StreamId
	slog.Info("handle finish received", "streamId", streamId, "id", c.id)
	if stream, err := stream.Mux.RemoveStream(streamId); err != nil {
		slog.Error("handleInformFinish:", "err", err, "streamId", streamId, "id", c.id)
	} else {
		stream.Logger.Info("handleInformFinish: stream removed", "streamId", streamId, "id", c.id)
		stream.Close()
	}
}

// handleInformTeardown is called when the client sends a teardown message
// this should happen when the client is shutting down and wants to close
// all streams
func (c *Connection) handleInformTeardown(teardown *pb.ServerInformTeardownRequest) {
	slog.Debug("handle teardown received", "id", c.id)
	close(c.teardownChan)
	stream.Mux.FinishAndCloseAllStreams(teardown.ExitCode)
}
