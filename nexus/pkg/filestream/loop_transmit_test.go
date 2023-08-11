package filestream

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"strings"
	"testing"

	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"golang.org/x/exp/slog"

	"github.com/wandb/wandb/nexus/internal/clienttest"
	"github.com/wandb/wandb/nexus/pkg/observability"
)

func requestMatch(t *testing.T, fsd FsData) func(*http.Request) (*http.Response, error) {
	resp := http.Response{
		StatusCode:    200,
		Body:          io.NopCloser(strings.NewReader("")),
		ContentLength: 0,
	}
	return func(req *http.Request) (*http.Response, error) {
		p := FsData{}
		err := json.NewDecoder(req.Body).Decode(&p)
		assert.Nil(t, err)
		assert.Equal(t, fsd.Files, p.Files)
		return &resp, nil
	}
}

func testSendAndReceive(t *testing.T, chunk chunkData, fsd FsData) {
	ctrl := gomock.NewController(t)

	m := clienttest.NewMockRoundTripper(ctrl)
	m.EXPECT().
		RoundTrip(gomock.Any()).
		DoAndReturn(requestMatch(t, fsd)).
		AnyTimes()

	slogger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	logger := observability.NewNexusLogger(slogger, nil)
	fs := NewFileStream(
		WithLogger(logger),
		WithHttpClient(clienttest.NewMockRetryClient(m)),
	)
	fs.sendChunkList([]chunkData{chunk})
}

func TestSendChunks(t *testing.T) {
	chunk := chunkData{
		fileName: HistoryFileName,
		fileData: &chunkLine{
			chunkType: HistoryChunk,
			line:      "blllah",
		},
	}
	fsd := FsData{Files: map[string]FsChunkData{
		"wandb-history.jsonl": FsChunkData{
			Offset:  0,
			Content: []string{"blllah"},
		},
	},
	}
	testSendAndReceive(t, chunk, fsd)
}
