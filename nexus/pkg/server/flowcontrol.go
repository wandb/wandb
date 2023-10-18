package server

import (
	"github.com/wandb/wandb/nexus/pkg/fsm"
	"github.com/wandb/wandb/nexus/pkg/service"
)

type FlowControlContext struct {
	// last offset forwarded to the sender
	forwardedOffset int64
	// last offset reported by the sender as sent
	sentOffset int64
	// last offset written to the transaction log
	writtenOffset int64
}

const (
	// By default we will allow 512 MiB of requests in the sender queue
	// before falling back to the transaction log.
	DefaultNetworkBuffer = 512 * 1024 * 1024 // 512 MiB
)

type FlowControl struct {
	stateMachine *fsm.Fsm[*service.Record, *FlowControlContext]
}

type StateShared struct {
	context    FlowControlContext
	sendRecord func(record *service.Record)
}

type StateForwarding struct {
	fsm.FsmState[*service.Record, *FlowControlContext]
	StateShared
	sendPause      func()
	thresholdPause int64
}

type StatePausing struct {
	fsm.FsmState[*service.Record, *FlowControlContext]
	StateShared
	recoverRecords   func(int64, int64)
	thresholdRecover int64
	thresholdForward int64
}

func isControlRecord(record *service.Record) bool {
	return record.Control.FlowControl
}

func isLocalNonControlRecord(record *service.Record) bool {
	return record.Control.Local && !record.Control.FlowControl
}

func (c FlowControlContext) behindBytes() int64 {
	return c.forwardedOffset - c.sentOffset
}

func (s *StateShared) processRecord(record *service.Record) {
	s.context.writtenOffset = record.Control.EndOffset
	// keep track of sent_offset if this is a status report
	if req, ok := record.RecordType.(*service.Record_Request); ok {
		if statusReport, ok := req.Request.RequestType.(*service.Request_StatusReport); ok {
			s.context.sentOffset = statusReport.StatusReport.SentOffset
		}
	}
}

func (s *StateShared) forwardRecord(record *service.Record) {
	s.context.forwardedOffset = record.Control.EndOffset
	if !isControlRecord(record) {
		s.sendRecord(record)
	}
}

func (s *StateShared) OnEnter(record *service.Record, context *FlowControlContext) {
	s.context = *context
}

func (s *StateShared) OnExit(record *service.Record) *FlowControlContext {
	return &s.context
}

func (s *StateForwarding) OnCheck(record *service.Record) {
	s.processRecord(record)
	s.forwardRecord(record)
}

func (s *StateForwarding) shouldPause(record *service.Record) bool {
	return s.context.behindBytes() >= s.thresholdPause
}

func (s *StateForwarding) doPause(record *service.Record) {
	s.sendPause()
}

func (s *StatePausing) OnCheck(record *service.Record) {
	s.processRecord(record)
}

func (s *StatePausing) shouldUnpause(record *service.Record) bool {
	return s.context.behindBytes() < s.thresholdForward
}

func (s *StatePausing) doUnpause(record *service.Record) {
	s.doQuiesce(record)
}

func (s *StatePausing) shouldRecover(record *service.Record) bool {
	return s.context.behindBytes() < s.thresholdRecover
}

func (s *StatePausing) doRecover(record *service.Record) {
	s.doQuiesce(record)
}

func (s *StatePausing) shouldQuiesce(record *service.Record) bool {
	return isLocalNonControlRecord(record)
}

func (s *StatePausing) doQuiesce(record *service.Record) {
	startOffset := s.context.forwardedOffset
	endOffset := s.context.writtenOffset
	if startOffset != endOffset {
		s.recoverRecords(startOffset, endOffset)
	}
	if isLocalNonControlRecord(record) {
		s.forwardRecord(record)
	}
	// update offset TODO: is this right?
	s.context.forwardedOffset = record.Control.EndOffset
}

func NewFlowControl(settings *service.Settings, sendRecord func(record *service.Record), sendPause func(),
                    recoverRecords func(int64, int64)) *FlowControl {
	var networkBuffer int64 = DefaultNetworkBuffer
	if param := settings.GetXNetworkBuffer(); param != nil {
		networkBuffer = int64(param.GetValue())
	}
	thresholdPause := networkBuffer
	thresholdRecover := networkBuffer / 2
	thresholdForward := networkBuffer / 4
	flowControl := &FlowControl{}

	stateMachine := fsm.NewFsm[*service.Record, *FlowControlContext]()
	forwarding := &StateForwarding{
		StateShared: StateShared{
			sendRecord: sendRecord,
		},
		sendPause:      sendPause,
		thresholdPause: thresholdPause,
	}
	pausing := &StatePausing{
		StateShared: StateShared{
			sendRecord: sendRecord,
		},
		recoverRecords:   recoverRecords,
		thresholdRecover: thresholdRecover,
		thresholdForward: thresholdForward,
	}
	stateMachine.SetDefaultState(forwarding)
	stateMachine.AddState(forwarding)
	stateMachine.AddState(pausing)

	forwarding.AddTransition(forwarding.shouldPause, pausing, forwarding.doPause)
	pausing.AddTransition(pausing.shouldUnpause, forwarding, pausing.doUnpause)
	pausing.AddTransition(pausing.shouldRecover, forwarding, pausing.doRecover)
	pausing.AddTransition(pausing.shouldQuiesce, forwarding, pausing.doQuiesce)

	flowControl.stateMachine = stateMachine
	return flowControl
}

func (f *FlowControl) Flow(record *service.Record) {
	f.stateMachine.Input(record)
}
