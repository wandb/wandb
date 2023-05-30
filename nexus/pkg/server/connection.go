package server

import (
	"bufio"
	"bytes"
	"context"
	"encoding/binary"
	"net"

	"github.com/sirupsen/logrus"
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
	conn   net.Conn
	server *NexusServer
	done   chan bool
	ctx    context.Context

	mux         map[string]*Stream
	processChan chan *service.ServerRequest
	respondChan chan *service.ServerResponse
}

func (nc *NexusConn) init(ctx context.Context) {
	process := make(chan *service.ServerRequest)
	respond := make(chan *service.ServerResponse)
	nc.processChan = process
	nc.respondChan = respond
	nc.done = make(chan bool)
	nc.ctx = ctx
	nc.mux = make(map[string]*Stream)
}

func checkError(e error) {
	if e != nil {
		logrus.Error(e)
	}
}

func (x *Tokenizer) split(data []byte, atEOF bool) (retAdvance int, retToken []byte, retErr error) {
	if x.headerLength == 0 {
		x.headerLength = binary.Size(x.header)
	}

	retAdvance = 0

	if !x.headerValid {
		if len(data) < x.headerLength {
			return
		}
		buf := bytes.NewReader(data)
		err := binary.Read(buf, binary.LittleEndian, &x.header)
		if err != nil {
			logrus.Error(err)
			return 0, nil, err
		}
		if x.header.Magic != uint8('W') {
			logrus.Error("Invalid magic byte in header")
		}
		x.headerValid = true
		retAdvance += x.headerLength
		data = data[retAdvance:]
	}

	if len(data) < int(x.header.DataLength) {
		return
	}

	retAdvance += int(x.header.DataLength)
	retToken = data[:x.header.DataLength]
	x.headerValid = false
	return
}

func respondServerResponse(ctx context.Context, nc *NexusConn, msg *service.ServerResponse) {
	out, err := proto.Marshal(msg)
	checkError(err)

	writer := bufio.NewWriter(nc.conn)

	header := Header{Magic: byte('W')}
	header.DataLength = uint32(len(out))

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
			logrus.Error("Unmarshaling error: ", err)
			break
		}
		nc.processChan <- msg
	}
	logrus.Debugf("SOCKETREADER: DONE")
	nc.done <- true
}

func (nc *NexusConn) transmit(ctx context.Context) {
	for {
		select {
		case msg := <-nc.respondChan:
			respondServerResponse(ctx, nc, msg)
		case <-nc.done:
			logrus.Debug("PROCESS: DONE")
			return
		}
	}
}

func (nc *NexusConn) process(ctx context.Context) {
	for {
		select {
		case msg := <-nc.processChan:
			handleServerRequest(nc, msg)
		case <-nc.done:
			logrus.Debug("PROCESS: DONE")
			return
		case <-ctx.Done():
			logrus.Debug("PROCESS: Context canceled")
			nc.done <- true
			return
		}
	}
}

func (nc *NexusConn) RespondServerResponse(ctx context.Context, serverResponse *service.ServerResponse) {
	nc.respondChan <- serverResponse
}

func (nc *NexusConn) wait(ctx context.Context) {
	logrus.Debug("WAIT1")
	for {
		select {
		case <-nc.done:
			logrus.Debug("WAIT done")
			return
		case <-ctx.Done():
			logrus.Debug("WAIT ctx done")
			return
		}
	}
}

func handleConnection(ctx context.Context, serverState *NexusServer, conn net.Conn) {
	defer func() {
		conn.Close()
	}()

	connection := NexusConn{conn: conn, server: serverState}

	connection.init(ctx)
	go connection.receive(ctx)
	go connection.transmit(ctx)
	go connection.process(ctx)
	connection.wait(ctx)

	logrus.Debug("WAIT3 done handle con")
}
