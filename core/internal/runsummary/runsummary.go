package runsummary

import (
	"encoding/json"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunSummaryDict = pathtree.TreeData

type RunSummary struct {
	*pathtree.PathTree[*service.SummaryItem]
}

func New() *RunSummary {
	return &RunSummary{PathTree: pathtree.New[*service.SummaryItem]()}
}

func NewFrom(tree RunSummaryDict) *RunSummary {
	return &RunSummary{PathTree: pathtree.NewFrom[*service.SummaryItem](tree)}
}

func (runSummary *RunSummary) ApplyChangeRecord(
	summaryRecord *service.SummaryRecord,
	onError func(error),
) {
	update := summaryRecord.GetUpdate()
	runSummary.ApplyUpdate(update, onError)

	remove := summaryRecord.GetRemove()
	runSummary.ApplyRemove(remove, onError)
}

func (runSummary *RunSummary) Serialize(format pathtree.Format) ([]byte, error) {
	return runSummary.PathTree.Serialize(format, nil)
}

// TODO: fix this to build nested tree and include remove
func (runSummary *RunSummary) FlattenTree() []*service.SummaryItem {
	var update []*service.SummaryItem
	for key, val := range runSummary.Tree() {

		value, err := json.Marshal(val)
		if err != nil {
			continue
		}
		update = append(update,
			&service.SummaryItem{
				Key:       key,
				ValueJson: string(value),
			},
		)
	}

	return update
}
