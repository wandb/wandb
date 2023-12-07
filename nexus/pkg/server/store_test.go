package server_test

import (
	"context"
	"io"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/server"
	"github.com/wandb/wandb/nexus/pkg/service"
)

func TestStoreHeaderReadWrite(t *testing.T) {
	header := server.StoreHeader{}

	r, w := io.Pipe()

	go func() {
		defer w.Close()
		err := header.Write(w)
		assert.NoError(t, err)
	}()

	err := header.Read(r)
	assert.NoError(t, err)
	headerString := header.GetIdent()
	assert.Equal(t, server.HeaderIdent, string(headerString[:]))
	assert.Equal(t, uint16(server.HeaderMagic), header.GetMagic())
	assert.Equal(t, byte(server.HeaderVersion), header.GetVersion())
	_ = r.Close()
}

func TestOpenCreateStore(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNexusLogger(server.SetupDefaultLogger(), nil)
	store := server.NewStore(context.Background(), tmpFile.Name(), logger)
	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)
}

func TestOpenReadStore(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNexusLogger(server.SetupDefaultLogger(), nil)
	store := server.NewStore(context.Background(), tmpFile.Name(), logger)
	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	store2 := server.NewStore(context.Background(), tmpFile.Name(), logger)
	err = store2.Open(os.O_RDONLY)
	assert.NoError(t, err)

	err = store2.Close()
	assert.NoError(t, err)
}

func TestReadWriteRecord(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNexusLogger(server.SetupDefaultLogger(), nil)
	store := server.NewStore(context.Background(), tmpFile.Name(), logger)
	defer store.Close()

	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	record := &service.Record{Num: 1, Uuid: "test-uuid"}

	err = store.Write(record)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	store2 := server.NewStore(context.Background(), tmpFile.Name(), logger)
	err = store2.Open(os.O_RDONLY)
	assert.NoError(t, err)
	defer store2.Close()

	readRecord, err := store2.Read()
	assert.NoError(t, err)

	assert.Equal(t, record.Control, readRecord.Control)
	assert.Equal(t, record.Num, readRecord.Num)
	assert.Equal(t, record.Uuid, readRecord.Uuid)
	err = store2.Close()
	assert.NoError(t, err)
}

func TestCorruptFile(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNexusLogger(server.SetupDefaultLogger(), nil)
	store := server.NewStore(context.Background(), tmpFile.Name(), logger)
	defer store.Close()

	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	record := &service.Record{Num: 1, Uuid: "test-uuid"}
	err = store.Write(record)
	assert.NoError(t, err)

	_, err = store.WriteDirectlyToDB([]byte("bad record"))
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	store2 := server.NewStore(context.Background(), tmpFile.Name(), logger)
	err = store2.Open(os.O_RDONLY)
	assert.NoError(t, err)
	defer store2.Close()

	_, err = store2.Read()
	assert.Error(t, err)

	err = store2.Close()
	assert.NoError(t, err)
}
