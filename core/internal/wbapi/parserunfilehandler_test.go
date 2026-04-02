package wbapi

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func writeTestFile(t *testing.T, records ...*spb.Record) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "run.wandb")
	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	for _, r := range records {
		require.NoError(t, writer.Write(r))
	}
	require.NoError(t, writer.Close())
	return path
}

func TestParseRunFile_InitAndCleanup(t *testing.T) {
	path := writeTestFile(t, &spb.Record{
		Num:        1,
		RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "abc"}},
	})

	handler := NewParseRunFileHandler()

	initResp := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileInit{
			ParseRunFileInit: &spb.ParseRunFileInit{Path: path},
		},
	})
	require.NotNil(t, initResp)
	require.Nil(t, initResp.GetApiErrorResponse())

	requestId := initResp.GetParseRunFileResponse().GetParseRunFileInit().GetRequestId()
	assert.Greater(t, requestId, int32(0))

	cleanupResp := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileCleanup{
			ParseRunFileCleanup: &spb.ParseRunFileCleanup{RequestId: requestId},
		},
	})
	assert.Nil(t, cleanupResp, "cleanup is fire-and-forget, no response")
}

func TestParseRunFile_ReadRecords(t *testing.T) {
	path := writeTestFile(t,
		&spb.Record{
			Num:        1,
			RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "test-run"}},
		},
		&spb.Record{
			Num: 2,
			RecordType: &spb.Record_History{
				History: &spb.HistoryRecord{
					Item: []*spb.HistoryItem{{Key: "loss", ValueJson: "0.5"}},
				},
			},
		},
		&spb.Record{
			Num:        3,
			RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}},
		},
	)

	handler := NewParseRunFileHandler()

	initResp := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileInit{
			ParseRunFileInit: &spb.ParseRunFileInit{Path: path},
		},
	})
	requestId := initResp.GetParseRunFileResponse().GetParseRunFileInit().GetRequestId()

	readResp := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileRead{
			ParseRunFileRead: &spb.ParseRunFileRead{
				RequestId: requestId,
				PageSize:  10,
			},
		},
	})
	require.NotNil(t, readResp)
	require.Nil(t, readResp.GetApiErrorResponse())

	page := readResp.GetParseRunFileResponse().GetParseRunFileRead()
	assert.True(t, page.Eof)
	assert.Len(t, page.Records, 3)
	assert.Equal(t, "run", page.Records[0].RecordType)
	assert.Equal(t, int64(1), page.Records[0].RecordNum)
	assert.Equal(t, "history", page.Records[1].RecordType)
	assert.Equal(t, "exit", page.Records[2].RecordType)

	assert.Contains(t, page.Records[0].JsonContent, "test-run")
	assert.Contains(t, page.Records[1].JsonContent, "loss")
}

func TestParseRunFile_Pagination(t *testing.T) {
	path := writeTestFile(t,
		&spb.Record{Num: 1, RecordType: &spb.Record_Run{Run: &spb.RunRecord{}}},
		&spb.Record{Num: 2, RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{}}},
	)

	handler := NewParseRunFileHandler()

	initResp := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileInit{
			ParseRunFileInit: &spb.ParseRunFileInit{Path: path},
		},
	})
	requestId := initResp.GetParseRunFileResponse().GetParseRunFileInit().GetRequestId()

	// Read one at a time
	read1 := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileRead{
			ParseRunFileRead: &spb.ParseRunFileRead{
				RequestId: requestId,
				PageSize:  1,
			},
		},
	})
	page1 := read1.GetParseRunFileResponse().GetParseRunFileRead()
	assert.Len(t, page1.Records, 1)
	assert.False(t, page1.Eof)
	assert.Equal(t, "run", page1.Records[0].RecordType)

	read2 := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileRead{
			ParseRunFileRead: &spb.ParseRunFileRead{
				RequestId: requestId,
				PageSize:  1,
			},
		},
	})
	page2 := read2.GetParseRunFileResponse().GetParseRunFileRead()
	assert.Len(t, page2.Records, 1)
	assert.False(t, page2.Eof, "EOF is only discovered on the next read")
	assert.Equal(t, "exit", page2.Records[0].RecordType)

	// Third read discovers EOF
	read3 := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileRead{
			ParseRunFileRead: &spb.ParseRunFileRead{
				RequestId: requestId,
				PageSize:  1,
			},
		},
	})
	page3 := read3.GetParseRunFileResponse().GetParseRunFileRead()
	assert.Len(t, page3.Records, 0)
	assert.True(t, page3.Eof)
}

func TestParseRunFile_RecordTypeFilter(t *testing.T) {
	path := writeTestFile(t,
		&spb.Record{Num: 1, RecordType: &spb.Record_Run{Run: &spb.RunRecord{}}},
		&spb.Record{Num: 2, RecordType: &spb.Record_History{History: &spb.HistoryRecord{}}},
		&spb.Record{Num: 3, RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{}}},
	)

	handler := NewParseRunFileHandler()

	initResp := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileInit{
			ParseRunFileInit: &spb.ParseRunFileInit{Path: path},
		},
	})
	requestId := initResp.GetParseRunFileResponse().GetParseRunFileInit().GetRequestId()

	readResp := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileRead{
			ParseRunFileRead: &spb.ParseRunFileRead{
				RequestId:   requestId,
				PageSize:    10,
				RecordTypes: []string{"history"},
			},
		},
	})
	page := readResp.GetParseRunFileResponse().GetParseRunFileRead()
	assert.True(t, page.Eof)
	assert.Len(t, page.Records, 1)
	assert.Equal(t, "history", page.Records[0].RecordType)
}

func TestParseRunFile_InitBadPath(t *testing.T) {
	handler := NewParseRunFileHandler()

	resp := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileInit{
			ParseRunFileInit: &spb.ParseRunFileInit{Path: "/nonexistent/file.wandb"},
		},
	})
	require.NotNil(t, resp.GetApiErrorResponse())
	assert.Contains(t, resp.GetApiErrorResponse().Message, "no such file")
}

func TestParseRunFile_ReadBadRequestId(t *testing.T) {
	handler := NewParseRunFileHandler()

	resp := handler.HandleRequest(&spb.ParseRunFileRequest{
		Request: &spb.ParseRunFileRequest_ParseRunFileRead{
			ParseRunFileRead: &spb.ParseRunFileRead{
				RequestId: 9999,
				PageSize:  10,
			},
		},
	})
	require.NotNil(t, resp.GetApiErrorResponse())
	assert.Contains(t, resp.GetApiErrorResponse().Message, "not initialized")
}
