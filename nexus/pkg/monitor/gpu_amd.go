// go:build linux && !libwandb_core

package monitor

import (
	"encoding/json"
	"fmt"
	"log"
	"os/exec"
	"strings"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/service"
)

// TODO: this is a port of the python code
// should eventually switch to https://github.com/amd/go_amd_smi

const rocmSMICmd string = "/usr/bin/rocm-smi"

type StatsKeys string

const (
	GPU             StatsKeys = "gpu"
	MemoryAllocated StatsKeys = "memoryAllocated"
	Temp            StatsKeys = "temp"
	PowerWatts      StatsKeys = "powerWatts"
	PowerPercent    StatsKeys = "powerPercent"
)

type Stats map[StatsKeys]float64

type InfoDict map[string]interface{}

type GPUAMD struct {
	name     string
	settings *service.Settings
	samples  []Stats
	mutex    sync.Mutex
}

func NewGPUAMD(settings *service.Settings) *GPUAMD {
	return &GPUAMD{
		name:     "gpu",
		settings: settings,
		samples:  make([]Stats, 0),
	}
}

func (g *GPUAMD) Name() string { return g.name }

func (g *GPUAMD) IsAvailable() bool {
	_, err := exec.LookPath(rocmSMICmd)
	return err == nil
}

func (g *GPUAMD) Probe() *service.MetadataRequest {
	return nil
}

func getROCMSMIStats() (InfoDict, error) {
	cmd := exec.Command(rocmSMICmd, "-a", "--json")
	output, err := cmd.Output()
	if err != nil {
		return nil, err
	}

	var stats InfoDict
	err = json.Unmarshal(output, &stats)
	if err != nil {
		return nil, err
	}
	return stats, nil
}

func (g *GPUAMD) parseStats(stats map[string]interface{}) Stats {
	parsedStats := make(Stats)

	for key, val := range stats {
		strVal, ok := val.(string)
		if !ok {
			// Optionally handle the error if the value is not a string
			log.Printf("Value for key %s is not a string", key)
			continue
		}

		var err error
		var floatValue float64

		// Process the string value based on the key
		switch key {
		case "GPU use (%)":
			floatValue, err = parseFloat(strVal)
			if err == nil {
				parsedStats[GPU] = floatValue
			}
		case "GPU memory use (%)":
			floatValue, err = parseFloat(strVal)
			if err == nil {
				parsedStats[MemoryAllocated] = floatValue
			}
		case "Temperature (Sensor memory) (C)":
			floatValue, err = parseFloat(strVal)
			if err == nil {
				parsedStats[Temp] = floatValue
			}
		case "Average Graphics Package Power (W)":
			powerWatts, err := parseFloat(strVal)
			if err == nil {
				parsedStats[PowerWatts] = powerWatts
			}
			// Add other cases as needed
		}

		// You can add more complex processing here, such as handling the "Max Graphics Package Power (W)" case
	}

	return parsedStats
}

func (g *GPUAMD) SampleMetrics() {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	rawStats, err := getROCMSMIStats()
	if err != nil {
		log.Printf("Error getting ROCm SMI stats: %v", err)
		return
	}

	var cards []Stats
	for key, value := range rawStats {
		if strings.HasPrefix(key, "card") {
			cardStats, ok := value.(map[string]interface{})
			if !ok {
				log.Printf("Type assertion failed for key %s", key)
				continue
			}
			stats := g.parseStats(cardStats)
			cards = append(cards, stats)
		}
	}

	if len(cards) > 0 {
		g.samples = append(g.samples, cards...)
	}
}

func parseFloat(s string) (float64, error) {
	var f float64
	_, err := fmt.Sscanf(s, "%f", &f)
	return f, err
}

func (g *GPUAMD) ClearMetrics() {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	g.samples = make([]Stats, 0)
}

func (g *GPUAMD) AggregateMetrics() map[string]float64 {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	aggregates := make(map[string]float64)
	for _, sample := range g.samples {
		for key, value := range sample {
			aggregates[string(key)] += value
		}
	}

	for key := range aggregates {
		aggregates[key] /= float64(len(g.samples))
	}

	return aggregates
}
