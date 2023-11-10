package nexuslib

import (
	"encoding/json"
	"fmt"

	"github.com/wandb/wandb/nexus/pkg/service"
)

// Generic item which works with summary and history
type GenericItem interface {
	GetKey() string
	GetValueJson() string
}

func JsonifyItems[V GenericItem](items []V) (string, error) {
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

func ConsolidateSummaryItems[V GenericItem](consolidatedSummary map[string]string, items []V) *service.Record {
	var summaryItems []*service.SummaryItem

	for _, item := range items {
		key := item.GetKey()
		value := item.GetValueJson()
		consolidatedSummary[key] = value
		summaryItems = append(summaryItems,
			&service.SummaryItem{
				Key:       key,
				ValueJson: value})
	}

	record := &service.Record{
		RecordType: &service.Record_Summary{
			Summary: &service.SummaryRecord{
				Update: summaryItems,
			},
		},
	}
	return record
}
