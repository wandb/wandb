package server

import (
	"context"
	"encoding/binary"
	"io"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	"github.com/wandb/wandb/core/internal/sweeps/schedulertest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// newSchedulerTestConn wires a Connection with a scheduler broker over a
// pipe, returning the pipe's client side and a channel closed once the
// connection has unwound.
func newSchedulerTestConn(
	t *testing.T,
	factory scheduler.TaskResolverFactory,
) (net.Conn, <-chan struct{}) {
	t.Helper()

	serverConn, clientConn := net.Pipe()
	t.Cleanup(func() { _ = serverConn.Close() })
	t.Cleanup(func() { _ = clientConn.Close() })
	require.NoError(t,
		clientConn.SetDeadline(time.Now().Add(schedulertest.ReceiveTimeout)))

	broker := scheduler.NewIPCSessionBroker(
		factory, observabilitytest.NewTestLogger(t))

	conn := NewConnection(
		context.Background(),
		func() {},
		ConnectionParams{
			ID:               "test",
			Conn:             serverConn,
			SweepSchedBroker: broker,
		},
	)

	unwound := make(chan struct{})
	go func() {
		defer close(unwound)
		conn.ManageConnectionData()
	}()
	return clientConn, unwound
}

func writeServerRequest(
	t *testing.T,
	conn net.Conn,
	request *spb.ServerRequest,
) {
	t.Helper()

	payload, err := proto.Marshal(request)
	require.NoError(t, err)

	header := Header{Magic: byte('W'), DataLength: uint32(len(payload))}
	require.NoError(t, binary.Write(conn, binary.LittleEndian, &header))
	_, err = conn.Write(payload)
	require.NoError(t, err)
}

func readServerResponse(
	t *testing.T,
	conn net.Conn,
) *spb.ServerResponse {
	t.Helper()

	var header Header
	require.NoError(t, binary.Read(conn, binary.LittleEndian, &header))
	payload := make([]byte, header.DataLength)
	_, err := io.ReadFull(conn, payload)
	require.NoError(t, err)

	response := &spb.ServerResponse{}
	require.NoError(t, proto.Unmarshal(payload, response))
	return response
}

func TestConnection_SweepSchedulerRouting(t *testing.T) {
	resolver := schedulertest.NewMockTaskResolver(gomock.NewController(t))
	// The first poll carries no result; the one after the stop does.
	resolver.EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		Return(&spb.SweepSchedulerServerNextTaskResponse{
			Task: &spb.SweepSchedulerServerNextTaskResponse_Generation{
				Generation: &spb.SweepSchedulerServerGenerationTask{},
			},
		})
	// The expectation is the assertion that the stop was routed.
	resolver.EXPECT().Stop()
	resolver.EXPECT().
		Step(gomock.Any(), gomock.Not(gomock.Nil())).
		Return(&spb.SweepSchedulerServerNextTaskResponse{
			Task: &spb.SweepSchedulerServerNextTaskResponse_Done{
				Done: &spb.SweepSchedulerServerDoneTask{
					Reason: spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
				},
			},
		})

	clientConn, unwound := newSchedulerTestConn(t, func(
		schedCtx context.Context,
		reqCtx context.Context,
		req *spb.SweepSchedulerClientInitRequest,
	) (scheduler.TaskResolver, *spb.SweepSchedulerServerInitResponse, error) {
		return resolver, &spb.SweepSchedulerServerInitResponse{
			SweepConfig: "method: grid",
		}, nil
	})

	// Init assigns a scheduler id and echoes the sweep config.
	writeServerRequest(t, clientConn, &spb.ServerRequest{
		RequestId: "req-init",
		ServerRequestType: &spb.ServerRequest_SweepSchedulerInit{
			SweepSchedulerInit: &spb.SweepSchedulerClientInitRequest{
				Entity: "e", Project: "p", SweepId: "s",
			},
		},
	})
	initResponse := readServerResponse(t, clientConn)
	assert.Equal(t, "req-init", initResponse.RequestId)
	init := initResponse.GetSweepSchedulerInitResponse()
	require.NotNil(t, init)
	assert.Equal(t, "method: grid", init.SweepConfig)

	// The long poll routes to the session and gets a task.
	writeServerRequest(t, clientConn, &spb.ServerRequest{
		RequestId: "req-task",
		ServerRequestType: &spb.ServerRequest_SweepSchedulerNextTask{
			SweepSchedulerNextTask: &spb.SweepSchedulerClientNextTaskRequest{
				SessionId: init.SessionId,
			},
		},
	})
	taskResponse := readServerResponse(t, clientConn)
	assert.Equal(t, "req-task", taskResponse.RequestId)
	task := taskResponse.GetSweepSchedulerNextTaskResponse()
	require.NotNil(t, task)
	require.NotNil(t, task.GetGeneration())

	// Stop is fire-and-forget; the next poll observes it. The result
	// echoes the outstanding task so the machine advances.
	writeServerRequest(t, clientConn, &spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_SweepSchedulerStop{
			SweepSchedulerStop: &spb.SweepSchedulerClientStopRequest{
				SessionId: init.SessionId,
			},
		},
	})
	writeServerRequest(t, clientConn, &spb.ServerRequest{
		RequestId: "req-final",
		ServerRequestType: &spb.ServerRequest_SweepSchedulerNextTask{
			SweepSchedulerNextTask: &spb.SweepSchedulerClientNextTaskRequest{
				SessionId: init.SessionId,
				Result: &spb.SweepSchedulerClientTaskResult{
					TaskSeq: task.TaskSeq,
					Result: &spb.SweepSchedulerClientTaskResult_Generation{
						Generation: &spb.SweepSchedulerClientGenerationResult{},
					},
				},
			},
		},
	})
	doneResponse := readServerResponse(t, clientConn)
	assert.Equal(t, "req-final", doneResponse.RequestId)
	done := doneResponse.GetSweepSchedulerNextTaskResponse().GetDone()
	require.NotNil(t, done)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN, done.Reason)

	// Closing the client unwinds the connection promptly even though a
	// scheduler session exists.
	require.NoError(t, clientConn.Close())
	schedulertest.Receive(t, unwound)
}

func TestConnection_SweepSchedulerInitErrorResponse(t *testing.T) {
	clientConn, unwound := newSchedulerTestConn(t, func(
		schedCtx context.Context,
		reqCtx context.Context,
		req *spb.SweepSchedulerClientInitRequest,
	) (scheduler.TaskResolver, *spb.SweepSchedulerServerInitResponse, error) {
		return nil, nil, scheduler.ErrUnsupportedServer
	})

	writeServerRequest(t, clientConn, &spb.ServerRequest{
		RequestId: "req-init",
		ServerRequestType: &spb.ServerRequest_SweepSchedulerInit{
			SweepSchedulerInit: &spb.SweepSchedulerClientInitRequest{},
		},
	})
	response := readServerResponse(t, clientConn)

	assert.Equal(t, "req-init", response.RequestId)
	require.NotNil(t, response.GetErrorResponse())
	assert.Contains(t,
		response.GetErrorResponse().Message, "does not support")

	require.NoError(t, clientConn.Close())
	schedulertest.Receive(t, unwound)
}
