//go:build unix

package listeners

import (
	"errors"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestUnixSocketListener_CloseRemovesDir(t *testing.T) {
	var portInfo PortInfo

	listener, err := listenInTempDir("wandb-test-*", &portInfo)
	require.NoError(t, err)

	sockDir := filepath.Dir(portInfo.UnixPath)
	require.NoError(t, listener.Close())

	_, err = os.Stat(sockDir)
	require.True(t, os.IsNotExist(err))
}

func TestMakeUnixListener_SetsPortInfoUnixPath(t *testing.T) {
	var portInfo PortInfo
	listener, err := makeUnixListener(os.Getpid(), &portInfo)
	require.NoError(t, err)
	t.Cleanup(func() { _ = listener.Close() })

	sockDir := filepath.Dir(portInfo.UnixPath)
	wantPath := filepath.Join(sockDir, "socket")
	require.Equal(t, portInfo.UnixPath, wantPath)
	require.NoError(t, listener.Close())
	_, err = os.Stat(sockDir)
	require.True(t, os.IsNotExist(err))
}

func TestUnixSocketListener_CloseUnblocksAccept(t *testing.T) {
	var portInfo PortInfo

	listener, err := listenInTempDir("wandb-test-*", &portInfo)
	require.NoError(t, err)

	acceptDone := make(chan error, 1)
	go func() {
		_, acceptErr := listener.Accept()
		acceptDone <- acceptErr
	}()

	time.Sleep(50 * time.Millisecond)
	require.NoError(t, listener.Close())

	select {
	case acceptErr := <-acceptDone:
		require.Error(t, acceptErr)
		require.True(t, errors.Is(acceptErr, net.ErrClosed))
	case <-time.After(2 * time.Second):
		t.Fatal("Accept did not return after Close; underlying listener was not closed")
	}
}
