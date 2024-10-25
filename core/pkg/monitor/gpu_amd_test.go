//go:build linux

package monitor_test

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/pkg/monitor"
)

func TestNewGPUAMD(t *testing.T) {
	logger := observability.NewNoOpLogger()
	gpu := monitor.NewGPUAMD(logger)
	assert.NotNil(t, gpu)
	assert.Equal(t, "gpu", gpu.Name())
}

func TestGPUAMD_ParseStatsROCM5(t *testing.T) {
	logger := observability.NewNoOpLogger()
	gpu := monitor.NewGPUAMD(logger)
	stats := map[string]interface{}{
		"GPU use (%)":                        "10",
		"GPU memory use (%)":                 "20",
		"Temperature (Sensor memory) (C)":    "43.0",
		"Average Graphics Package Power (W)": "89.0",
		"Max Graphics Package Power (W)":     "560.0",
	}
	parsedStats := gpu.ParseStats(stats)

	expected := monitor.Stats{
		monitor.GPUUtilization:  10,
		monitor.MemoryAllocated: 20,
		monitor.Temp:            43,
		monitor.PowerWatts:      89,
		monitor.PowerPercent:    15.892857142857142,
	}

	assert.Equal(t, expected, parsedStats)
}

func TestGPUAMD_ParseStatsROCM6(t *testing.T) {
	logger := observability.NewNoOpLogger()
	gpu := monitor.NewGPUAMD(logger)
	stats := map[string]interface{}{
		"GPU use (%)":                        "10",
		"GPU Memory Allocated (VRAM%)":       "20",
		"Temperature (Sensor memory) (C)":    "43.0",
		"Average Graphics Package Power (W)": "89.0",
		"Max Graphics Package Power (W)":     "560.0",
	}
	parsedStats := gpu.ParseStats(stats)

	expected := monitor.Stats{
		monitor.GPUUtilization:  10,
		monitor.MemoryAllocated: 20,
		monitor.Temp:            43,
		monitor.PowerWatts:      89,
		monitor.PowerPercent:    15.892857142857142,
	}

	assert.Equal(t, expected, parsedStats)
}

func TestGPUAMD_ParseStatsROCM6_MI300x(t *testing.T) {
	logger := observability.NewNoOpLogger()
	gpu := monitor.NewGPUAMD(logger)
	stats := map[string]interface{}{
		"GPU use (%)":                               "10",
		"GPU Memory Allocated (VRAM%)":              "20",
		"Temperature (Sensor memory) (C)":           "43.0",
		"Current Socket Graphics Package Power (W)": "89.0",
		"Max Graphics Package Power (W)":            "560.0",
	}
	parsedStats := gpu.ParseStats(stats)

	expected := monitor.Stats{
		monitor.GPUUtilization:  10,
		monitor.MemoryAllocated: 20,
		monitor.Temp:            43,
		monitor.PowerWatts:      89,
		monitor.PowerPercent:    15.892857142857142,
	}

	assert.Equal(t, expected, parsedStats)
}

func getROCMSMIStatsROCM5Mock() (monitor.InfoDict, error) {
	jsonString := `{"card0": {"GPU ID": "0x740c", "Unique ID": "0x719d230578348e8c", "VBIOS version": "113-D65209-073", "Temperature (Sensor edge) (C)": "32.0", "Temperature (Sensor junction) (C)": "35.0", "Temperature (Sensor memory) (C)": "43.0", "Temperature (Sensor HBM 0) (C)": "43.0", "Temperature (Sensor HBM 1) (C)": "39.0", "Temperature (Sensor HBM 2) (C)": "42.0", "Temperature (Sensor HBM 3) (C)": "43.0", "fclk clock speed:": "(400Mhz)", "fclk clock level:": "0", "mclk clock speed:": "(1600Mhz)", "mclk clock level:": "3", "sclk clock speed:": "(800Mhz)", "sclk clock level:": "1", "socclk clock speed:": "(1090Mhz)", "socclk clock level:": "3", "Performance Level": "auto", "GPU OverDrive value (%)": "0", "GPU Memory OverDrive value (%)": "0", "Max Graphics Package Power (W)": "560.0", "Average Graphics Package Power (W)": "89.0", "GPU use (%)": "10", "GFX Activity": "2469071528", "GPU memory use (%)": "0", "Memory Activity": "2189510857", "GPU memory vendor": "hynix", "PCIe Replay Count": "147", "Serial Number": "PCB052715-0065", "Voltage (mV)": "818", "PCI Bus": "0000:2F:00.0", "ASD firmware version": "0x00000000", "CE firmware version": "0", "DMCU firmware version": "0", "MC firmware version": "0", "ME firmware version": "0", "MEC firmware version": "78", "MEC2 firmware version": "78", "PFP firmware version": "0", "RLC firmware version": "17", "RLC SRLC firmware version": "0", "RLC SRLG firmware version": "0", "RLC SRLS firmware version": "0", "SDMA firmware version": "8", "SDMA2 firmware version": "8", "SMC firmware version": "00.68.59.00", "SOS firmware version": "0x00270082", "TA RAS firmware version": "27.00.01.60", "TA XGMI firmware version": "32.00.00.15", "UVD firmware version": "0x00000000", "VCE firmware version": "0x00000000", "VCN firmware version": "0x0110101b", "Card series": "AMD INSTINCT MI250 (MCM) OAM AC MBA", "Card model": "0x0b0c", "Card vendor": "Advanced Micro Devices, Inc. [AMD/ATI]", "Card SKU": "D65209", "Valid sclk range": "500Mhz - 1700Mhz", "Valid mclk range": "400Mhz - 1600Mhz", "Voltage point 0": "0Mhz 0mV", "Voltage point 1": "0Mhz 0mV", "Voltage point 2": "0Mhz 0mV", "Energy counter": "62929744071539", "Accumulated Energy (uJ)": "962825096297442.9"}, "card1": {"GPU ID": "0x740c", "Unique ID": "0x719d230578348e8c", "VBIOS version": "113-D65209-073", "Temperature (Sensor edge) (C)": "32.0", "Temperature (Sensor junction) (C)": "35.0", "Temperature (Sensor memory) (C)": "43.0", "Temperature (Sensor HBM 0) (C)": "43.0", "Temperature (Sensor HBM 1) (C)": "39.0", "Temperature (Sensor HBM 2) (C)": "42.0", "Temperature (Sensor HBM 3) (C)": "43.0", "fclk clock speed:": "(400Mhz)", "fclk clock level:": "0", "mclk clock speed:": "(1600Mhz)", "mclk clock level:": "3", "sclk clock speed:": "(800Mhz)", "sclk clock level:": "1", "socclk clock speed:": "(1090Mhz)", "socclk clock level:": "3", "Performance Level": "auto", "GPU OverDrive value (%)": "0", "GPU Memory OverDrive value (%)": "0", "Max Graphics Package Power (W)": "560.0", "Average Graphics Package Power (W)": "89.0", "GPU use (%)": "20", "GFX Activity": "2469071528", "GPU memory use (%)": "0", "Memory Activity": "2189510857", "GPU memory vendor": "hynix", "PCIe Replay Count": "147", "Serial Number": "PCB052715-0065", "Voltage (mV)": "818", "PCI Bus": "0000:2F:00.0", "ASD firmware version": "0x00000000", "CE firmware version": "0", "DMCU firmware version": "0", "MC firmware version": "0", "ME firmware version": "0", "MEC firmware version": "78", "MEC2 firmware version": "78", "PFP firmware version": "0", "RLC firmware version": "17", "RLC SRLC firmware version": "0", "RLC SRLG firmware version": "0", "RLC SRLS firmware version": "0", "SDMA firmware version": "8", "SDMA2 firmware version": "8", "SMC firmware version": "00.68.59.00", "SOS firmware version": "0x00270082", "TA RAS firmware version": "27.00.01.60", "TA XGMI firmware version": "32.00.00.15", "UVD firmware version": "0x00000000", "VCE firmware version": "0x00000000", "VCN firmware version": "0x0110101b", "Card series": "AMD INSTINCT MI250 (MCM) OAM AC MBA", "Card model": "0x0b0c", "Card vendor": "Advanced Micro Devices, Inc. [AMD/ATI]", "Card SKU": "D65209", "Valid sclk range": "500Mhz - 1700Mhz", "Valid mclk range": "400Mhz - 1600Mhz", "Voltage point 0": "0Mhz 0mV", "Voltage point 1": "0Mhz 0mV", "Voltage point 2": "0Mhz 0mV", "Energy counter": "62929744071539", "Accumulated Energy (uJ)": "962825096297442.9"}, "system": {"Driver version": "6.2.4"}}`

	infoDict := monitor.InfoDict{}
	err := json.Unmarshal([]byte(jsonString), &infoDict)
	if err != nil {
		return nil, err
	}
	return infoDict, nil
}

func getROCMSMIStatsROCM6Mock() (monitor.InfoDict, error) {
	jsonString := `{"card0": {"Device Name": "AMD INSTINCT MI250 (MCM) OAM AC MBA", "Device ID": "0x740c", "Device Rev": "0x01", "Subsystem ID": "0x0b0c", "GUID": "64146", "Unique ID": "0x1f9de0957d137942", "VBIOS version": "113-D65209-073", "Temperature (Sensor edge) (C)": "43.0", "Temperature (Sensor junction) (C)": "44.0", "Temperature (Sensor memory) (C)": "53.0", "Temperature (Sensor HBM 0) (C)": "53.0", "Temperature (Sensor HBM 1) (C)": "50.0", "Temperature (Sensor HBM 2) (C)": "52.0", "Temperature (Sensor HBM 3) (C)": "52.0", "fclk clock speed:": "(400Mhz)", "fclk clock level:": "0", "mclk clock speed:": "(1600Mhz)", "mclk clock level:": "3", "sclk clock speed:": "(800Mhz)", "sclk clock level:": "1", "socclk clock speed:": "(1090Mhz)", "socclk clock level:": "3", "pcie clock level": "3 (2.5GT/s x8)", "Performance Level": "auto", "GPU OverDrive value (%)": "0", "GPU Memory OverDrive value (%)": "0", "Max Graphics Package Power (W)": "560.0", "Average Graphics Package Power (W)": "91.0", "GPU use (%)": "0", "GFX Activity": "387664097", "GPU Memory Allocated (VRAM%)": "0", "GPU Memory Read/Write Activity (%)": "0", "Memory Activity": "647284295", "Avg. Memory Bandwidth": "0", "GPU memory vendor": "hynix", "PCIe Replay Count": "3824", "Serial Number": "PCB052715-0006", "Voltage (mV)": "818", "PCI Bus": "0000:29:00.0", "ASD firmware version": "0x00000000", "CE firmware version": "0", "DMCU firmware version": "0", "MC firmware version": "0", "ME firmware version": "0", "MEC firmware version": "78", "MEC2 firmware version": "78", "PFP firmware version": "0", "RLC firmware version": "17", "RLC SRLC firmware version": "0", "RLC SRLG firmware version": "0", "RLC SRLS firmware version": "0", "SDMA firmware version": "8", "SDMA2 firmware version": "8", "SMC firmware version": "00.68.59.00", "SOS firmware version": "0x00270082", "TA RAS firmware version": "27.00.01.60", "TA XGMI firmware version": "32.00.00.15", "UVD firmware version": "0x00000000", "VCE firmware version": "0x00000000", "VCN firmware version": "0x0110101b", "Card Series": "AMD INSTINCT MI250 (MCM) OAM AC MBA", "Card Model": "0x740c", "Card Vendor": "Advanced Micro Devices, Inc. [AMD/ATI]", "Card SKU": "D65209", "Node ID": "2", "GFX Version": "gfx9010", "Valid sclk range": "500Mhz - 1700Mhz", "Valid mclk range": "400Mhz - 1600Mhz", "Energy counter": "279426720261621", "Accumulated Energy (uJ)": "4275228873299218.5"}, "system": {"Driver version": "6.2.4"}}`

	infoDict := monitor.InfoDict{}
	err := json.Unmarshal([]byte(jsonString), &infoDict)
	if err != nil {
		return nil, err
	}
	return infoDict, nil
}

func TestGPUAMD_SampleStats(t *testing.T) {
	testCases := []struct {
		mockFunc    func() (monitor.InfoDict, error)
		expectedLen int
	}{
		{getROCMSMIStatsROCM5Mock, 12},
		{getROCMSMIStatsROCM6Mock, 7},
	}

	for _, tc := range testCases {
		logger := observability.NewNoOpLogger()
		gpu := monitor.NewGPUAMD(logger)
		gpu.GetROCMSMIStatsFunc = tc.mockFunc
		metrics, err := gpu.Sample()
		assert.Nil(t, err)
		assert.Len(t, metrics, tc.expectedLen)
	}
}

func TestGPUAMD_Probe(t *testing.T) {
	testCases := []struct {
		mockFunc func() (monitor.InfoDict, error)
		gpuCount uint32
		infoLen  int
	}{
		{getROCMSMIStatsROCM5Mock, uint32(2), 2},
		{getROCMSMIStatsROCM6Mock, uint32(1), 1},
	}
	for _, tc := range testCases {
		logger := observability.NewNoOpLogger()
		gpu := monitor.NewGPUAMD(logger)
		gpu.IsAvailableFunc = func() bool { return true }
		gpu.GetROCMSMIStatsFunc = tc.mockFunc
		info := gpu.Probe()
		assert.Equal(t, info.GpuCount, tc.gpuCount)
		assert.Len(t, info.GpuAmd, tc.infoLen)
	}
}
