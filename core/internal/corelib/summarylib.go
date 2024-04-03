package corelib

import (
	"fmt"

	// TODO: use simplejsonext for now until we replace the usage of json with
	// protocol buffer and proto json marshaler
	json "github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/pkg/service"
)

// Generic item which works with summary and history
type genericItem interface {
	GetKey() string
	GetValueJson() string
}

func JsonifyItems[V genericItem](items []V) (string, error) {
	jsonMap := make(map[string]interface{})

	for _, item := range items {
		value, err := json.Unmarshal([]byte(item.GetValueJson()))
		if err != nil {
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

func ConsolidateSummaryItems[V genericItem](consolidatedSummary map[string]string, items []V) *service.Record {
	var summaryItems []*service.SummaryItem

	for i := 0; i < len(items); i++ {
		key := items[i].GetKey()
		value := items[i].GetValueJson()
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
