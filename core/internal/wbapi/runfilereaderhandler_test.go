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

func TestRunFileReader_InitAndCleanup(t *testing.T) {
	path := writeTestFile(t, &spb.Record{
		Num:        1,
		RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "abc"}},
	})
	handler := NewRunFileReaderHandler()

	initResp := handler.HandleRequest(&spb.RunFileReaderRequest{
		Request: &spb.RunFileReaderRequest_RunFileReaderInit{
			RunFileReaderInit: &spb.RunFileReaderInit{Path: path},
		},
	})
	require.NotNil(t, initResp)
	require.Nil(t, initResp.GetApiErrorResponse())

	requestId := initResp.GetRunFileReaderResponse().GetRunFileReaderInit().GetRequestId()

	handler.HandleRequest(&spb.RunFileReaderRequest{
		Request: &spb.RunFileReaderRequest_RunFileReaderCleanup{
			RunFileReaderCleanup: &spb.RunFileReaderCleanup{RequestId: requestId},
		},
	})
}

func TestRunFileReader_ReadRecords(t *testing.T) {
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

	handler := NewRunFileReaderHandler()

	initResp := handler.HandleRequest(&spb.RunFileReaderRequest{
		Request: &spb.RunFileReaderRequest_RunFileReaderInit{
			RunFileReaderInit: &spb.RunFileReaderInit{Path: path},
		},
	})
	requestId := initResp.GetRunFileReaderResponse().GetRunFileReaderInit().GetRequestId()

	readResp := handler.HandleRequest(&spb.RunFileReaderRequest{
		Request: &spb.RunFileReaderRequest_RunFileReaderRead{
			RunFileReaderRead: &spb.RunFileReaderRead{
				RequestId: requestId,
				PageSize:  10,
			},
		},
	})
	require.NotNil(t, readResp)
	require.Nil(t, readResp.GetApiErrorResponse())

	page := readResp.GetRunFileReaderResponse().GetRunFileReaderRead()
	assert.False(t, page.HasMore)
	assert.Len(t, page.Records, 3)
	expected := []struct {
		recordType string
		recordNum  int64
		json       string
	}{
		{"run", 1, `{"num":"1","run":{"run_id":"test-run"}}`},
		{"history", 2, `{"num":"2","history":{"item":[{"key":"loss","value_json":"0.5"}]}}`},
		{"exit", 3, `{"num":"3","exit":{}}`},
	}
	for i, exp := range expected {
		assert.Equal(t, exp.recordType, page.Records[i].RecordType)
		assert.Equal(t, exp.recordNum, page.Records[i].RecordNum)
		assert.JSONEq(t, exp.json, page.Records[i].JsonContent)
	}
}

func TestRunFileReader_Pagination(t *testing.T) {
	path := writeTestFile(t,
		&spb.Record{Num: 1, RecordType: &spb.Record_Run{Run: &spb.RunRecord{}}},
		&spb.Record{Num: 2, RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{}}},
	)

	handler := NewRunFileReaderHandler()

	initResp := handler.HandleRequest(&spb.RunFileReaderRequest{
		Request: &spb.RunFileReaderRequest_RunFileReaderInit{
			RunFileReaderInit: &spb.RunFileReaderInit{Path: path},
		},
	})
	requestId := initResp.GetRunFileReaderResponse().GetRunFileReaderInit().GetRequestId()

	pages := []struct {
		count      int
		hasMore    bool
		recordType string
	}{
		{1, true, "run"},
		{1, true, "exit"},
		{0, false, ""},
	}
	for _, exp := range pages {
		resp := handler.HandleRequest(&spb.RunFileReaderRequest{
			Request: &spb.RunFileReaderRequest_RunFileReaderRead{
				RunFileReaderRead: &spb.RunFileReaderRead{
					RequestId: requestId,
					PageSize:  1,
				},
			},
		})
		page := resp.GetRunFileReaderResponse().GetRunFileReaderRead()
		assert.Len(t, page.Records, exp.count)
		assert.Equal(t, exp.hasMore, page.HasMore)
		if exp.count > 0 {
			assert.Equal(t, exp.recordType, page.Records[0].RecordType)
		}
	}
}

func TestRunFileReader_RecordTypeFilter(t *testing.T) {
	path := writeTestFile(t,
		&spb.Record{Num: 1, RecordType: &spb.Record_Run{Run: &spb.RunRecord{}}},
		&spb.Record{Num: 2, RecordType: &spb.Record_History{History: &spb.HistoryRecord{}}},
		&spb.Record{Num: 3, RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{}}},
	)

	handler := NewRunFileReaderHandler()

	initResp := handler.HandleRequest(&spb.RunFileReaderRequest{
		Request: &spb.RunFileReaderRequest_RunFileReaderInit{
			RunFileReaderInit: &spb.RunFileReaderInit{Path: path},
		},
	})
	requestId := initResp.GetRunFileReaderResponse().GetRunFileReaderInit().GetRequestId()

	readResp := handler.HandleRequest(&spb.RunFileReaderRequest{
		Request: &spb.RunFileReaderRequest_RunFileReaderRead{
			RunFileReaderRead: &spb.RunFileReaderRead{
				RequestId:   requestId,
				PageSize:    10,
				RecordTypes: []string{"history"},
			},
		},
	})
	page := readResp.GetRunFileReaderResponse().GetRunFileReaderRead()
	assert.False(t, page.HasMore)
	assert.Len(t, page.Records, 1)
	assert.Equal(t, "history", page.Records[0].RecordType)
}

func TestRunFileReader_InitBadPath(t *testing.T) {
	handler := NewRunFileReaderHandler()

	resp := handler.HandleRequest(&spb.RunFileReaderRequest{
		Request: &spb.RunFileReaderRequest_RunFileReaderInit{
			RunFileReaderInit: &spb.RunFileReaderInit{Path: "/nonexistent/file.wandb"},
		},
	})
	require.NotNil(t, resp.GetApiErrorResponse())
	assert.Contains(t, resp.GetApiErrorResponse().Message, "no such file")
}

func TestRunFileReader_ReadBadRequestId(t *testing.T) {
	handler := NewRunFileReaderHandler()

	resp := handler.HandleRequest(&spb.RunFileReaderRequest{
		Request: &spb.RunFileReaderRequest_RunFileReaderRead{
			RunFileReaderRead: &spb.RunFileReaderRead{
				RequestId: 9999,
				PageSize:  10,
			},
		},
	})
	require.NotNil(t, resp.GetApiErrorResponse())
	assert.Contains(t, resp.GetApiErrorResponse().Message, "has not been initialized")
}
