package server

import (
	"fmt"
	"github.com/wandb/wandb/nexus/service"
	"strconv"
	// log "github.com/sirupsen/logrus"
)

func (h *Handler) handleRunStart(rec *service.Record, req *service.RunStartRequest) {
	h.startTime = float64(req.Run.StartTime.AsTime().UnixMicro()) / 1e6
}

func (h *Handler) handlePartialHistory(rec *service.Record, req *service.PartialHistoryRequest) {

	step_num := h.currentStep
	h.currentStep += 1
	s := service.HistoryStep{Num: step_num}
	items := req.Item

	var runTime float64
	runTime = 0

	// walk through items looking for _timestamp
	for i := 0; i < len(items); i++ {
		if items[i].Key == "_timestamp" {
			val, err := strconv.ParseFloat(items[i].ValueJson, 64)
			check(err)
			runTime = val - h.startTime
		}
	}
	items2 := append(items,
		&service.HistoryItem{Key: "_runtime", ValueJson: fmt.Sprintf("%f", runTime)},
		&service.HistoryItem{Key: "_step", ValueJson: fmt.Sprintf("%d", step_num)},
	)

	hrecord := service.HistoryRecord{Step: &s, Item: items2}

	// TODO: add _runtime and _step

	// from runstartrequest
	//    self._run_start_time = run_start.run.start_time.ToMicroseconds() / 1e6

	r := service.Record{
		RecordType: &service.Record_History{&hrecord},
	}
	h.storeRecord(&r)
}
