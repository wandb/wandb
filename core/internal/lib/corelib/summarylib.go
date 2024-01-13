package corelib

import (
	"fmt"

	"github.com/segmentio/encoding/json"

	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

// Generic item which works with summary and history
type genericItem interface {
	GetKey() string
	GetValueJson() string
}

func JsonifyItems[V genericItem](items []V) (string, error) {
	jsonMap := make(map[string]interface{})

	for _, item := range items {
		var value interface{}
		if err := json.Unmarshal([]byte(item.GetValueJson()), &value); err != nil {
			e := fmt.Errorf("json unmarshal error: %v, items: %v", err, item)
			return "", e
		}
		jsonMap[item.GetKey()] = value
	}

	jsonBytes, err := json.Marshal(jsonMap)
	if err != nil {
		return "", err
	}
	return string(jsonBytes), nil
}

func ConsolidateSummaryItems[V genericItem](consolidatedSummary map[string]string, items []V) *pb.Record {
	var summaryItems []*pb.SummaryItem

	for i := 0; i < len(items); i++ {
		key := items[i].GetKey()
		value := items[i].GetValueJson()
		consolidatedSummary[key] = value
		summaryItems = append(summaryItems,
			&pb.SummaryItem{
				Key:       key,
				ValueJson: value})
	}

	record := &pb.Record{
		RecordType: &pb.Record_Summary{
			Summary: &pb.SummaryRecord{
				Update: summaryItems,
			},
		},
	}
	return record
}
