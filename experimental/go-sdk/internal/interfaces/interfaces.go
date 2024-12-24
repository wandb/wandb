package interfaces

import (
	"encoding/json"
	"sync"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"github.com/wandb/wandb/experimental/go-sdk/internal/connection"
	"github.com/wandb/wandb/experimental/go-sdk/internal/mailbox"
	"github.com/wandb/wandb/experimental/go-sdk/pkg/runconfig"
	"github.com/wandb/wandb/experimental/go-sdk/pkg/settings"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type IRun struct {
	Conn     *connection.Connection
	wg       sync.WaitGroup
	StreamID string
}

func (r *IRun) Start() {
	r.wg.Add(1)
	go func() {
		r.Conn.Recv()
		r.wg.Done()
	}()
}

func (r *IRun) Close() {
	r.Conn.Close()
	r.wg.Wait()
}

// InformInit sends an init message to the server.
func (r *IRun) InformInit(settings *settings.Settings) {
	r.Conn.Send(&spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_InformInit{
			InformInit: &spb.ServerInformInitRequest{
				Settings: settings.ToProto(),
				XInfo: &spb.XRecordInfo{
					StreamId: r.StreamID,
				},
			},
		},
	})
}

// InformStart sends a start message to the server.
func (r *IRun) InformStart(settings *settings.Settings) {
	r.Conn.Send(&spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_InformStart{
			InformStart: &spb.ServerInformStartRequest{
				XInfo: &spb.XRecordInfo{
					StreamId: r.StreamID,
				},
			},
		},
	})
}

func (r *IRun) InformFinish(settings *settings.Settings) {
	r.Conn.Send(&spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_InformFinish{
			InformFinish: &spb.ServerInformFinishRequest{
				XInfo: &spb.XRecordInfo{
					StreamId: r.StreamID,
				},
			},
		},
	})
}

func (r *IRun) InformTeardown() {
	r.Conn.Send(&spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_InformTeardown{
			InformTeardown: &spb.ServerInformTeardownRequest{
				XInfo: &spb.XRecordInfo{
					StreamId: r.StreamID,
				},
			},
		},
	})
}

// DeliverRunRecord delivers a run record to the server.
func (r *IRun) DeliverRunRecord(settings *settings.Settings, config *runconfig.Config) *mailbox.MailboxHandle {
	configRecord := &spb.ConfigRecord{}
	if config != nil {
		for key, value := range *config {
			data, err := json.Marshal(value)
			if err != nil {
				panic(err)
			}
			configRecord.Update = append(configRecord.Update, &spb.ConfigItem{
				Key:       key,
				ValueJson: string(data),
			})
		}
	}
	record := spb.Record{
		RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{
				RunId:       settings.RunID,
				Entity:      settings.Entity,
				Project:     settings.RunProject,
				RunGroup:    settings.RunGroup,
				JobType:     settings.RunJobType,
				DisplayName: settings.RunName,
				Notes:       settings.RunNotes,
				Tags:        settings.RunTags,
				Config:      configRecord,
				StartTime:   timestamppb.New(settings.GetStartTime()),
				XInfo: &spb.XRecordInfo{
					StreamId: r.StreamID,
				},
			},
		},
		XInfo: &spb.XRecordInfo{
			StreamId: r.StreamID,
		},
	}
	handle := r.Conn.Mailbox.Deliver(&record)
	r.Conn.Send(&spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_RecordCommunicate{
			RecordCommunicate: &record,
		},
	})
	return handle
}

func (r *IRun) DeliverRunStartRequest(settings *settings.Settings) *mailbox.MailboxHandle {
	record := spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_RunStart{
					RunStart: &spb.RunStartRequest{
						Run: &spb.RunRecord{
							RunId:     r.StreamID,
							StartTime: timestamppb.New(settings.GetStartTime()),
						},
					},
				},
			},
		},
		Control: &spb.Control{Local: true},
		XInfo: &spb.XRecordInfo{
			StreamId: r.StreamID,
		},
	}
	handle := r.Conn.Mailbox.Deliver(&record)
	r.Conn.Send(&spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_RecordCommunicate{
			RecordCommunicate: &record,
		},
	})
	return handle
}

// DeliverExitRecord sends an exit message to the server.
func (r *IRun) DeliverExitRecord() *mailbox.MailboxHandle {
	record := spb.Record{
		RecordType: &spb.Record_Exit{
			Exit: &spb.RunExitRecord{
				ExitCode: 0,
				XInfo: &spb.XRecordInfo{
					StreamId: r.StreamID,
				},
			},
		},
		XInfo: &spb.XRecordInfo{
			StreamId: r.StreamID,
		},
	}
	serverRecord := spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_RecordCommunicate{
			RecordCommunicate: &record,
		},
	}
	handle := r.Conn.Mailbox.Deliver(&record)
	r.Conn.Send(&serverRecord)
	return handle
}

func (r *IRun) DeliverShutdownRecord() *mailbox.MailboxHandle {
	record := &spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_Shutdown{
					Shutdown: &spb.ShutdownRequest{},
				},
			},
		},
		Control: &spb.Control{
			AlwaysSend: true,
			ReqResp:    true,
		},
		XInfo: &spb.XRecordInfo{
			StreamId: r.StreamID,
		},
	}
	serverRecord := spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_RecordCommunicate{
			RecordCommunicate: record,
		},
	}
	handle := r.Conn.Mailbox.Deliver(record)
	r.Conn.Send(&serverRecord)
	return handle
}

func (r *IRun) PublishPartialHistory(data map[string]interface{}) {
	history := spb.PartialHistoryRequest{}
	for key, value := range data {
		// strValue := strconv.FormatFloat(value, 'f', -1, 64)
		data, err := json.Marshal(value)
		if err != nil {
			panic(err)
		}
		history.Item = append(history.Item, &spb.HistoryItem{
			Key:       key,
			ValueJson: string(data),
		})
	}

	record := spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_RecordPublish{
			RecordPublish: &spb.Record{
				RecordType: &spb.Record_Request{
					Request: &spb.Request{
						RequestType: &spb.Request_PartialHistory{
							PartialHistory: &history,
						},
					},
				},
				Control: &spb.Control{
					Local: true,
				},
				XInfo: &spb.XRecordInfo{
					StreamId: r.StreamID,
				},
			}},
	}
	r.Conn.Send(&record)
}
