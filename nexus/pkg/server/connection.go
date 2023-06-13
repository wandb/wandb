package server

import (
	"bufio"
	"bytes"
	"context"
	"encoding/binary"
	"net"
	"sync"

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

type Connection struct {
	ctx    context.Context
	cancel context.CancelFunc
	conn   net.Conn

	shutdownChan chan<- bool
	requestChan  chan *service.ServerRequest
	respondChan  chan *service.ServerResponse
}

func NewConnection(
	ctx context.Context,
	cancel context.CancelFunc,
	conn net.Conn,
	shutdownChan chan<- bool,
) *Connection {
	return &Connection{
		ctx:          ctx,
		cancel:       cancel,
		conn:         conn,
		shutdownChan: shutdownChan,
		requestChan:  make(chan *service.ServerRequest),
		respondChan:  make(chan *service.ServerResponse),
	}
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

func respondServerResponse(nc *Connection, msg *service.ServerResponse) {
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

func (nc *Connection) receive(wg *sync.WaitGroup) {
	defer wg.Done()

	scanner := bufio.NewScanner(nc.conn)
	tokenizer := Tokenizer{}
	scanner.Split(tokenizer.split)

	// Run Scanner in a separate goroutine to listen for incoming messages
	go func() {
		for scanner.Scan() {
			msg := &service.ServerRequest{}
			err := proto.Unmarshal(scanner.Bytes(), msg)
			if err != nil {
				log.Error("Unmarshalling error: ", err)
				continue
			}
			nc.requestChan <- msg
		}
		nc.cancel()
	}()

	// wait for context to be canceled
	<-nc.ctx.Done()

	log.Debugf("SOCKETREADER: DONE")
}

func (nc *Connection) transmit(wg *sync.WaitGroup) {
	defer wg.Done()

	for {
		select {
		case msg := <-nc.respondChan:
			respondServerResponse(nc, msg)
		case <-nc.ctx.Done():
			log.Debug("TRANSMIT: Context canceled")
			return
		}
	}
}

func (nc *Connection) process(wg *sync.WaitGroup) {
	defer wg.Done()

	for {
		select {
		case msg := <-nc.requestChan:
			nc.handleServerRequest(msg)
		case <-nc.ctx.Done():
			log.Debug("PROCESS: Context canceled")
			return
		}
	}
}

func (nc *Connection) RespondServerResponse(ctx context.Context, serverResponse *service.ServerResponse) {
	nc.respondChan <- serverResponse
}

func handleConnection(ctx context.Context, cancel context.CancelFunc, swg *sync.WaitGroup, conn net.Conn, shutdownChan chan<- bool) {
	connection := NewConnection(ctx, cancel, conn, shutdownChan)

	defer func() {
		swg.Done()
		err := connection.conn.Close()
		if err != nil {
			log.Error(err)
		}
		close(connection.requestChan)
		close(connection.respondChan)
	}()

	wg := sync.WaitGroup{}
	wg.Add(3)

	go connection.receive(&wg)
	go connection.transmit(&wg)
	go connection.process(&wg)

	wg.Wait()

	log.Debug("WAIT3 done handle con")
}

func (nc *Connection) handleInformInit(msg *service.ServerInformInitRequest) {
	log.Debug("PROCESS: INIT")

	s := msg.XSettingsMap
	settings := &Settings{
		BaseURL:  s["base_url"].GetStringValue(),
		ApiKey:   s["api_key"].GetStringValue(),
		SyncFile: s["sync_file"].GetStringValue(),
		Offline:  s["_offline"].GetBoolValue()}

	settings.parseNetrc()

	log.Debug("STREAM init")

	streamId := msg.XInfo.StreamId
	streamManager.addStream(streamId, nc.RespondServerResponse, settings)
}

func (nc *Connection) handleInformStart(msg *service.ServerInformStartRequest) {
	log.Debug("PROCESS: START")
}

func (nc *Connection) handleInformFinish(msg *service.ServerInformFinishRequest) {
	log.Debug("PROCESS: FIN")
	streamId := msg.XInfo.StreamId
	if stream, ok := streamManager.getStream(streamId); ok {
		stream.MarkFinished()
	} else {
		log.Debug("PROCESS: RECORD: stream not found")
	}
}

func (nc *Connection) handleInformRecord(msg *service.Record) {
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

func (nc *Connection) handleInformTeardown(msg *service.ServerInformTeardownRequest) {
	log.Debug("CONNECTION: TEARDOWN")
	streamManager.Close()
	log.Debug("CONNECTION: TEARDOWN: CLOSE")
	nc.cancel()
	log.Debug("CONNECTION: TEARDOWN: CANCEL")
	nc.shutdownChan <- true
	log.Debug("CONNECTION: TEARDOWN: DONE")
}

func (nc *Connection) handleServerRequest(msg *service.ServerRequest) {
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
