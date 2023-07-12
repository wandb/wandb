package server

import (
	"bufio"
	"context"
	"encoding/binary"
	"fmt"
	"net"
	"strings"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/auth"
	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
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

	// wg is the WaitGroup for the connection
	wg sync.WaitGroup

	// id is the unique id for the connection
	id string

	// inChan is the channel for incoming messages
	inChan chan *service.ServerRequest

	// outChan is the channel for outgoing messages
	outChan chan *service.ServerResponse

	// teardownChan is the channel for signaling teardown
	teardownChan chan struct{}

	// logger is the logger for the connection
	// logger slog.Logger
}

// NewConnection creates a new connection
func NewConnection(
	ctx context.Context,
	conn net.Conn,
	teardown chan struct{},
) *Connection {

	nc := &Connection{
		ctx:          ctx,
		wg:           sync.WaitGroup{},
		conn:         conn,
		id:           conn.RemoteAddr().String(), // TODO: check if this is properly unique
		inChan:       make(chan *service.ServerRequest),
		outChan:      make(chan *service.ServerResponse),
		teardownChan: teardown, //TODO: should we trigger teardown from a connection?
	}
	nc.wg.Add(1)
	go nc.handle()
	return nc
}

func (nc *Connection) handle() {
	slog.Info("created new connection", "id", nc.id)

	defer nc.wg.Done()

	nc.wg.Add(1)
	go func() {
		nc.handleServerRequest()
		nc.wg.Done()
	}()

	nc.wg.Add(1)
	go func() {
		nc.handleServerResponse()
		nc.wg.Done()
	}()
}

func (nc *Connection) Close() {
	slog.Debug("closing connection", "id", nc.id)
	if err := nc.conn.Close(); err != nil {
		slog.Error("error closing connection", "err", err, "id", nc.id)
	}
	nc.wg.Wait()
	slog.Info("closed connection", "id", nc.id)
}

func (nc *Connection) Respond(resp *service.ServerResponse) {
	nc.outChan <- resp
}

// handleServerRequest handles outgoing messages from the server
// to the client
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
func (nc *Connection) handleServerRequest() {
	defer close(nc.outChan)
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
		host := strings.TrimPrefix(s.GetBaseUrl().GetValue(), "https://")
		host = strings.TrimPrefix(host, "http://")

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
	stream := NewStream(nc.ctx, settings, streamId)
	stream.AddResponders(ResponderEntry{nc, nc.id})

	if err := streamMux.AddStream(streamId, stream); err != nil {
		slog.Error("connection init failed, stream already exists", "streamId", streamId, "id", nc.id)
		// TODO: should we Close the stream?
		return
	}
}

func (nc *Connection) handleInformStart(_ *service.ServerInformStartRequest) {
}

// handleInformAttach is called when the client sends an InformAttach message
func (nc *Connection) handleInformAttach(msg *service.ServerInformAttachRequest) {
	streamId := msg.GetXInfo().GetStreamId()
	slog.Debug("handle record received", "streamId", streamId, "id", nc.id)
	if stream, err := streamMux.GetStream(streamId); err != nil {
		slog.Error("handleInformAttach: stream not found", "streamId", streamId, "id", nc.id)
	} else {
		stream.AddResponders(ResponderEntry{nc, nc.id})
		// TODO: we should redo this attach logic, so that the stream handles
		//       the attach logic
		resp := &service.ServerResponse{
			ServerResponseType: &service.ServerResponse_InformAttachResponse{
				InformAttachResponse: &service.ServerInformAttachResponse{
					XInfo:    msg.XInfo,
					Settings: stream.settings,
				},
			},
		}
		nc.Respond(resp)
	}
}

// handleInformRecord is called when the client sends a record message
func (nc *Connection) handleInformRecord(msg *service.Record) {
	streamId := msg.GetXInfo().GetStreamId()
	slog.Debug("handle record received", "streamId", streamId, "id", nc.id)
	if stream, err := streamMux.GetStream(streamId); err != nil {
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
		stream.HandleRecord(msg)
	}
}

// handleInformFinish is called when the client sends a Close message
// for a stream
func (nc *Connection) handleInformFinish(msg *service.ServerInformFinishRequest) {
	streamId := msg.XInfo.StreamId
	slog.Info("handle finish received", "streamId", streamId, "id", nc.id)
	if stream, err := streamMux.RemoveStream(streamId); err != nil {
		slog.Error("handleInformFinish:", "err", err, "streamId", streamId, "id", nc.id)
	} else {
		stream.Close(false)
	}
}

// handleInformTeardown is called when the client sends a teardown message
// for the entire server session
func (nc *Connection) handleInformTeardown(_ *service.ServerInformTeardownRequest) {
	slog.Debug("handle teardown received", "id", nc.id)
	close(nc.teardownChan)
	streamMux.CloseAllStreams(true) // TODO: this seems wrong to Close all streams from a single connection
	nc.Close()
}
