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
	sendPause    func()
	pauseThreshold int64
}

type StatePausing struct {
	fsm.FsmState[*service.Record, *FlowControlContext]
	StateShared
	recoverThreshold int64
	forwardThreshold int64
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
	s.sendRecord(record)
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
	return s.context.behindBytes() >= s.pauseThreshold
}

func (s *StateForwarding) doPause(record *service.Record) {
	// self._pause_marker()
}

func (s *StatePausing) OnCheck(record *service.Record) {
	s.processRecord(record)
}

func (s *StatePausing) shouldUnpause(record *service.Record) bool {
	return false
}

func (s *StatePausing) doUnpause(record *service.Record) {
}

func (s *StatePausing) shouldRecover(record *service.Record) bool {
	return false
}

func (s *StatePausing) doRecover(record *service.Record) {
}

func (s *StatePausing) shouldQuiesce(record *service.Record) bool {
	return false
}

func (s *StatePausing) doQuiesce(record *service.Record) {
}

func NewFlowControl(sendRecord func(record *service.Record), sendPause func()) *FlowControl {
	flowControl := &FlowControl{}

	stateMachine := fsm.NewFsm[*service.Record, *FlowControlContext]()
	forwarding := &StateForwarding{
		StateShared: StateShared{
			sendRecord: sendRecord,
		},
		sendPause: sendPause,
	}
	pausing := &StatePausing{
		StateShared: StateShared{
			sendRecord: sendRecord,
		},
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
