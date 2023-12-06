// go:build linux && !libwandb_core

package monitor

/*
{"card0": {"GPU ID": "0x740c", "Unique ID": "0x719d230578348e8c", "VBIOS version": "113-D65209-073", "Temperature (Sensor edge) (C)": "32.0", "Temperature (Sensor junction) (C)": "35.0", "Temperature (Sensor memory) (C)": "43.0", "Temperature (Sensor HBM 0) (C)": "43.0", "Temperature (Sensor HBM 1) (C)": "39.0", "Temperature (Sensor HBM 2) (C)": "42.0", "Temperature (Sensor HBM 3) (C)": "43.0", "fclk clock speed:": "(400Mhz)", "fclk clock level:": "0", "mclk clock speed:": "(1600Mhz)", "mclk clock level:": "3", "sclk clock speed:": "(800Mhz)", "sclk clock level:": "1", "socclk clock speed:": "(1090Mhz)", "socclk clock level:": "3", "Performance Level": "auto", "GPU OverDrive value (%)": "0", "GPU Memory OverDrive value (%)": "0", "Max Graphics Package Power (W)": "560.0", "Average Graphics Package Power (W)": "89.0", "GPU use (%)": "0", "GFX Activity": "2469071528", "GPU memory use (%)": "0", "Memory Activity": "2189510857", "GPU memory vendor": "hynix", "PCIe Replay Count": "147", "Serial Number": "PCB052715-0065", "Voltage (mV)": "818", "PCI Bus": "0000:2F:00.0", "ASD firmware version": "0x00000000", "CE firmware version": "0", "DMCU firmware version": "0", "MC firmware version": "0", "ME firmware version": "0", "MEC firmware version": "78", "MEC2 firmware version": "78", "PFP firmware version": "0", "RLC firmware version": "17", "RLC SRLC firmware version": "0", "RLC SRLG firmware version": "0", "RLC SRLS firmware version": "0", "SDMA firmware version": "8", "SDMA2 firmware version": "8", "SMC firmware version": "00.68.59.00", "SOS firmware version": "0x00270082", "TA RAS firmware version": "27.00.01.60", "TA XGMI firmware version": "32.00.00.15", "UVD firmware version": "0x00000000", "VCE firmware version": "0x00000000", "VCN firmware version": "0x0110101b", "Card series": "AMD INSTINCT MI250 (MCM) OAM AC MBA", "Card model": "0x0b0c", "Card vendor": "Advanced Micro Devices, Inc. [AMD/ATI]", "Card SKU": "D65209", "Valid sclk range": "500Mhz - 1700Mhz", "Valid mclk range": "400Mhz - 1600Mhz", "Voltage point 0": "0Mhz 0mV", "Voltage point 1": "0Mhz 0mV", "Voltage point 2": "0Mhz 0mV", "Energy counter": "62929744071539", "Accumulated Energy (uJ)": "962825096297442.9"}, "system": {"Driver version": "6.2.4"}}
*/

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

func (g *GPUAMD) Samples() []Stats {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	return g.samples
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

func (g *GPUAMD) ParseStats(stats map[string]interface{}) Stats {
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
			stats := g.ParseStats(cardStats)
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

	if len(g.samples) == 0 {
		return nil
	}

	aggregates := make(map[string]float64)
	sampleCount := len(g.samples)

	// Iterate over each sample.
	for _, sample := range g.samples {
		// Iterate over each GPU in the sample.
		for gpuKey, gpuStats := range sample {
			// gpuKey is like "card0", "card1", etc.
			// gpuStats is a map of stats for this GPU.
			fmt.Println(gpuKey, gpuStats)
			// Iterate over each stat for this GPU.
			// for statKey, value := range gpuStats {
			// 	// statKey is the specific stat name.
			// 	// value is the value of this stat.

			// 	formattedKey := fmt.Sprintf("%s.%s", gpuKey, statKey)
			// 	aggregates[formattedKey] += value
			// }
		}
	}
	fmt.Println()
	// Calculate the averages.
	for key := range aggregates {
		aggregates[key] /= float64(sampleCount)
	}

	return aggregates
}
