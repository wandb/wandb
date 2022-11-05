package server

import (
    "github.com/wandb/wandb/nexus/service"
//    log "github.com/sirupsen/logrus"
)

/*
    def _flush_partial_history(
        self,
        step: Optional[int] = None,
    ) -> None:
        if self._partial_history:
            history = HistoryRecord()
            for k, v in self._partial_history.items():
                item = history.item.add()
                item.key = k
                item.value_json = json.dumps(v)
            if step is not None:
                history.step.num = step
            self.handle_history(Record(history=history))
            self._partial_history = {}

    def handle_request_partial_history(self, record: Record) -> None:
        partial_history = record.request.partial_history

        flush = None
        if partial_history.HasField("action"):
            flush = partial_history.action.flush

        step = None
        if partial_history.HasField("step"):
            step = partial_history.step.num

        history_dict = proto_util.dict_from_proto_list(partial_history.item)
        if step is not None:
            if step < self._step:
                logger.warning(
                    f"Step {step} < {self._step}. Dropping entry: {history_dict}."
                )
                return
            elif step > self._step:
                self._flush_partial_history()
                self._step = step
        elif flush is None:
            flush = True

        self._partial_history.update(history_dict)

        if flush:
            self._flush_partial_history(self._step)
 */
func (ns *Stream) handlePartialHistory(rec *service.Record, req *service.Request_PartialHistory) {
}


