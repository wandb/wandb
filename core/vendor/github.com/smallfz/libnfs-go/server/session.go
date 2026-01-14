package server

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net"

	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
	"github.com/smallfz/libnfs-go/xdr"
)

type SessionMux interface {
	HandleProc(*nfs.RPCMsgCall) (int, error)
}

type rpcHeader struct {
	Xid  uint32
	Type uint32
}

type Session struct {
	conn    net.Conn
	backend nfs.Backend
}

func (sess *Session) sendResponse(dat []byte) error {
	frag := uint32(len(dat)) | uint32(1<<31)
	writer := xdr.NewWriter(sess.conn)
	if _, err := writer.WriteUint32(frag); err != nil {
		return err
	}
	if _, err := writer.Write(dat); err != nil {
		return err
	}
	return nil
}

func (sess *Session) Conn() net.Conn {
	return sess.conn
}

func (sess *Session) Start(ctx context.Context) error {
	conn := sess.conn
	defer func() {
		conn.Close()
		log.Debugf("Disconnected from %v.", conn.RemoteAddr())
	}()

	backendSession := sess.backend.CreateSession(sess)
	defer backendSession.Close()

	auth := backendSession.Authentication()
	vfs := backendSession.GetFS()
	stat := backendSession.GetStatService()

	reader := xdr.NewReader(conn)

	for {
		frag, err := reader.ReadUint32()
		if err != nil {
			if err == io.EOF {
				return nil
			}
		}

		if frag&(1<<31) == 0 {
			return errors.New("(!)ignored: fragmented request")
		}

		headerSize := (frag << 1) >> 1
		restSize := int(headerSize)

		header := &nfs.RPCMsgCall{}
		if size, err := reader.ReadAs(header); err != nil {
			return fmt.Errorf("ReadAs(%T): %v", header, err)
		} else {
			restSize -= size
		}

		if header.MsgType != nfs.RPC_CALL {
			return errors.New("expecting a rpc call message")
		}

		// log.Infof("header: %v", header)

		mux := (SessionMux)(nil)

		buff := bytes.NewBuffer([]byte{})
		writer := xdr.NewWriter(buff)

		switch header.Vers {
		case 4:
			mux = &Muxv4{
				reader: reader,
				writer: writer,
				auth:   auth,
				fs:     vfs,
				stat:   stat,
			}

		case 3:
			mux = &Mux{
				reader: reader,
				writer: writer,
				auth:   auth,
				fs:     vfs,
				stat:   stat,
			}

		default:
			seq := []interface{}{
				&nfs.RPCMsgReply{
					Xid:       header.Xid,
					MsgType:   nfs.RPC_REPLY,
					ReplyStat: nfs.MSG_ACCEPTED,
				},
				nfs.NewEmptyAuth(),
				nfs.ACCEPT_PROG_MISMATCH,
				uint32(3), // low:  v3
				uint32(4), // high: v4
			}
			for _, v := range seq {
				if _, err := writer.WriteAny(v); err != nil {
					return err
				}
			}
		}

		if mux != nil {
			if size, err := mux.HandleProc(header); err != nil {
				return fmt.Errorf("mux.HandlerProc(%d): %v", header.Proc, err)
			} else {
				restSize -= size
			}
		} else {
			return errors.New("invalid rpc message: no suitable mux")
		}

		if err := sess.sendResponse(buff.Bytes()); err != nil {
			return fmt.Errorf("sendResponse: %v", err)
		}

		if restSize > 0 {
			log.Warnf("%d bytes unread.", restSize)
			if _, err := reader.ReadBytes(restSize); err != nil {
				if err == io.EOF {
					return nil
				}
			}
		}
	}
}

func handleSession(ctx context.Context, backend nfs.Backend, conn net.Conn) error {
	sess := &Session{
		conn:    conn,
		backend: backend,
	}
	return sess.Start(ctx)
}
