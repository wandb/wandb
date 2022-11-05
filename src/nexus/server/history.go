package server

import (
    "fmt"
    "strconv"
    "github.com/wandb/wandb/nexus/service"
//    log "github.com/sirupsen/logrus"
)

func (ns *Stream) handleRunStart(rec *service.Record, req *service.RunStartRequest) {
    ns.startTime = float64(req.Run.StartTime.AsTime().UnixMicro()) / 1e6
}

func (ns *Stream) handlePartialHistory(rec *service.Record, req *service.PartialHistoryRequest) {

    step_num := ns.currentStep
    ns.currentStep += 1
    s := service.HistoryStep{Num: step_num}
    items := req.Item


    var runTime float64
    runTime = 0

    // walk through items looking for _timestamp
    for i := 0; i < len(items); i++ {
        if items[i].Key == "_timestamp" {
            val, err := strconv.ParseFloat(items[i].ValueJson, 64)
            check(err)
            runTime = val - ns.startTime
        }
    }
    items2 := append(items,
        &service.HistoryItem{Key: "_runtime", ValueJson: fmt.Sprintf("%f", runTime)},
        &service.HistoryItem{Key: "_step", ValueJson: fmt.Sprintf("%d", step_num)},
    )

    h := service.HistoryRecord{Step: &s, Item: items2}

    // TODO: add _runtime and _step

    // from runstartrequest
    //    self._run_start_time = run_start.run.start_time.ToMicroseconds() / 1e6

    r := service.Record{
        RecordType: &service.Record_History{&h},
    }
    ns.storeRecord(&r)
}


