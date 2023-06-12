package server

import (
	"bufio"
	"bytes"
	"context"
	"encoding/binary"
	"net"

	log "github.com/sirupsen/logrus"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/proto"
)

type Header struct {
	Magic      uint8
	DataLength uint32
}

type Tokenizer struct {
	header       Header
	headerLength int
	headerValid  bool
}

type NexusConn struct {
	conn        net.Conn
	server      *NexusServer
	done        chan bool
	ctx         context.Context
	processChan chan *service.ServerRequest
	respondChan chan *service.ServerResponse
}

func (nc *NexusConn) init(ctx context.Context) {
	nc.processChan = make(chan *service.ServerRequest)
	nc.respondChan = make(chan *service.ServerResponse)
	nc.done = make(chan bool)
	nc.ctx = ctx
}

func checkError(e error) {
	if e != nil {
		log.Error(e)
	}
}

func (x *Tokenizer) split(data []byte, atEOF bool) (advance int, token []byte, err error) {
	if x.headerLength == 0 {
		x.headerLength = binary.Size(x.header)
	}

	advance = 0

	if !x.headerValid {
		if len(data) < x.headerLength {
			return
		}
		buf := bytes.NewReader(data)
		err := binary.Read(buf, binary.LittleEndian, &x.header)
		if err != nil {
			log.Error(err)
			return 0, nil, err
		}
		if x.header.Magic != uint8('W') {
			log.Error("Invalid magic byte in header")
		}
		x.headerValid = true
		advance += x.headerLength
		data = data[advance:]
	}

	if len(data) < int(x.header.DataLength) {
		return
	}

	advance += int(x.header.DataLength)
	token = data[:x.header.DataLength]
	x.headerValid = false
	return
}

func respondServerResponse(ctx context.Context, nc *NexusConn, msg *service.ServerResponse) {
	out, err := proto.Marshal(msg)
	checkError(err)

	writer := bufio.NewWriter(nc.conn)

	header := Header{Magic: byte('W'), DataLength: uint32(len(out))}

	err = binary.Write(writer, binary.LittleEndian, &header)
	checkError(err)

	_, err = writer.Write(out)
	checkError(err)

	err = writer.Flush()
	checkError(err)
}

func (nc *NexusConn) receive(ctx context.Context) {
	scanner := bufio.NewScanner(nc.conn)
	tokenizer := Tokenizer{}

	scanner.Split(tokenizer.split)
	for scanner.Scan() {
		msg := &service.ServerRequest{}
		err := proto.Unmarshal(scanner.Bytes(), msg)
		if err != nil {
			log.Error("Unmarshalling error: ", err)
			break
		}
		nc.processChan <- msg
	}
	log.Debugf("SOCKETREADER: DONE")
	nc.done <- true
}

func (nc *NexusConn) transmit(ctx context.Context) {
	for {
		select {
		case msg := <-nc.respondChan:
			respondServerResponse(ctx, nc, msg)
		case <-nc.done:
			log.Debug("PROCESS: DONE")
			return
		}
	}
}

func (nc *NexusConn) process(ctx context.Context) {
	for {
		select {
		case msg := <-nc.processChan:
			nc.handleServerRequest(msg)
		case <-nc.done:
			log.Debug("PROCESS: DONE")
			return
		case <-ctx.Done():
			log.Debug("PROCESS: Context canceled")
			nc.done <- true
			return
		}
	}
}

func (nc *NexusConn) RespondServerResponse(ctx context.Context, serverResponse *service.ServerResponse) {
	nc.respondChan <- serverResponse
}

func (nc *NexusConn) wait(ctx context.Context) {
	log.Debug("WAIT1")
	for {
		select {
		case <-nc.done:
			log.Debug("WAIT done")
			return
		case <-ctx.Done():
			log.Debug("WAIT ctx done")
			return
		}
	}
}

func handleConnection(ctx context.Context, serverState *NexusServer, conn net.Conn) {
	defer conn.Close()

	connection := NexusConn{conn: conn, server: serverState}

	connection.init(ctx)
	go connection.receive(ctx)
	go connection.transmit(ctx)
	go connection.process(ctx)
	connection.wait(ctx)

	log.Debug("WAIT3 done handle con")
}

func (nc *NexusConn) handleInformInit(msg *service.ServerInformInitRequest) {
	log.Debug("PROCESS: INIT")

	s := msg.XSettingsMap
	settings := &Settings{
		BaseURL:  s["base_url"].GetStringValue(),
		ApiKey:   s["api_key"].GetStringValue(),
		SyncFile: s["sync_file"].GetStringValue(),
		Offline:  s["_offline"].GetBoolValue()}

	settings.parseNetrc()

	// TODO make this a mapping
	log.Debug("STREAM init")
	// streamId := "thing"
	streamId := msg.XInfo.StreamId
	streamManager.addStream(streamId, nc.RespondServerResponse, settings)

	// read from mux and write to nc
	// go nc.mux[streamId].responder(nc)
}

func (nc *NexusConn) handleInformStart(msg *service.ServerInformStartRequest) {
	log.Debug("PROCESS: START")
}

func (nc *NexusConn) handleInformFinish(msg *service.ServerInformFinishRequest) {
	log.Debug("PROCESS: FIN")
	streamId := msg.XInfo.StreamId
	if stream, ok := streamManager.getStream(streamId); ok {
		stream.MarkFinished()
	} else {
		log.Debug("PROCESS: RECORD: stream not found")
	}
}

func (nc *NexusConn) handleInformRecord(msg *service.Record) {
	streamId := msg.XInfo.StreamId
	if stream, ok := streamManager.getStream(streamId); ok {
		ref := msg.ProtoReflect()
		desc := ref.Descriptor()
		num := ref.WhichOneof(desc.Oneofs().ByName("record_type")).Number()
		// fmt.Printf("PROCESS: COMM/PUBLISH %d\n", num)
		log.WithFields(log.Fields{"type": num}).Debug("PROCESS: COMM/PUBLISH")

		stream.ProcessRecord(msg)
	} else {
		log.Debug("PROCESS: RECORD: stream not found")
	}
}

func showFooter(result *service.Result, run *service.RunRecord, settings *Settings) {
	PrintHeadFoot(run, settings)
}

func finishAll(nc *NexusConn) {
	for _, stream := range streamManager.getStreams() {
		if stream.IsFinished() {
			continue
		}
		exitRecord := service.RunExitRecord{}
		record := service.Record{
			RecordType: &service.Record_Exit{Exit: &exitRecord},
		}
		handle := stream.Deliver(&record)
		got := handle.wait()
		settings := stream.GetSettings()
		run := stream.GetRun()
		showFooter(got, run, settings)
	}
}

func (nc *NexusConn) handleInformTeardown(msg *service.ServerInformTeardownRequest) {
	log.Debug("PROCESS: TEARDOWN")

	finishAll(nc)

	nc.done <- true
	// _, cancelCtx := context.WithCancel(nc.ctx)

	log.Debug("PROCESS: TEARDOWN *****1")
	// cancelCtx()
	log.Debug("PROCESS: TEARDOWN *****2")
	// TODO: remove this?
	// os.Exit(1)

	nc.server.shutdown = true
	nc.server.listen.Close()
}

func (nc *NexusConn) handleServerRequest(msg *service.ServerRequest) {
	switch x := msg.ServerRequestType.(type) {
	case *service.ServerRequest_InformInit:
		nc.handleInformInit(x.InformInit)
	case *service.ServerRequest_InformStart:
		nc.handleInformStart(x.InformStart)
	case *service.ServerRequest_InformFinish:
		nc.handleInformFinish(x.InformFinish)
	case *service.ServerRequest_RecordPublish:
		nc.handleInformRecord(x.RecordPublish)
	case *service.ServerRequest_RecordCommunicate:
		nc.handleInformRecord(x.RecordCommunicate)
	case *service.ServerRequest_InformTeardown:
		nc.handleInformTeardown(x.InformTeardown)
	case nil:
		// The field is not set.
		log.Fatal("ServerRequestType is nil")
	default:
		// The field is not set.
		log.Fatalf("ServerRequestType is unknown, %T", x)
	}
}
