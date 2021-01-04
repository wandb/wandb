//
//  definitions.h
//

#ifndef DEFINITIONS_H
#define DEFINITIONS_H

// Print Debugging Output
#undef XRG_DEBUG

typedef struct io_stats
{
    UInt64 bytes_delta;
    UInt64 bytes_prev;
    UInt64 bytes;
    UInt64 bsd_bytes_prev;
    UInt64 bsd_bytes;
} io_stats;

typedef struct network_interface_stats
{
    char if_name[32];
    struct io_stats if_in;
    struct io_stats if_out;
} network_interface_stats;

// Define the names of our saved settings
#define XRG_windowWidth @"windowWidth"
#define XRG_windowHeight @"windowHeight"
#define XRG_windowOriginX @"windowOriginX"
#define XRG_windowOriginY @"windowOriginY"

#define XRG_borderWidth @"borderWidth"
#define XRG_graphOrientationVertical @"graphOrientationVertical"
#define XRG_antiAliasing @"antiAliasing"
#define XRG_graphRefresh @"graphRefresh"
#define XRG_windowLevel @"windowLevel"
#define XRG_stickyWindow @"stickyWindow"
#define XRG_checkForUpdates @"checkForUpdates"
#define XRG_dropShadow @"dropShadow"
#define XRG_windowTitle @"windowTitle"
#define XRG_autoExpandGraph @"autoExpandGraph"
#define XRG_foregroundWhenExpanding @"foregroundWhenExpanding"
#define XRG_showSummary @"showSummary"
#define XRG_minimizeUpDown @"minimizeUpDown"
#define XRG_windowIsMinimized @"windowIsMinimized"
#define XRG_isDockIconHidden @"isDockIconHidden"

#define XRG_backgroundColor @"backgroundColor"
#define XRG_graphBGColor @"graphBGColor"
#define XRG_graphFG1Color @"graphFG1Color"
#define XRG_graphFG2Color @"graphFG2Color"
#define XRG_graphFG3Color @"graphFG3Color"
#define XRG_borderColor @"borderColor"
#define XRG_textColor @"textColor"
#define XRG_backgroundTransparency @"backgroundTransparency"
#define XRG_graphBGTransparency @"graphBGTransparency"
#define XRG_graphFG1Transparency @"graphFG1Transparency"
#define XRG_graphFG2Transparency @"graphFG2Transparency"
#define XRG_graphFG3Transparency @"graphFG3Transparency"
#define XRG_borderTransparency @"borderTransparency"
#define XRG_textTransparency @"textTransparency"
#define XRG_graphFont @"graphFont"
#define XRG_antialiasText @"antialiasText"

#define XRG_fastCPUUsage @"fastCPUUsage"
#define XRG_separateCPUColor @"separateCPUColor"
#define XRG_showCPUTemperature @"showCPUTemperature"
#define XRG_cpuTemperatureUnits @"cpuTemperatureUnits"
#define XRG_showLoadAverage @"showLoadAverage"
#define XRG_cpuShowAverageUsage @"cpuShowAverageUsage"
#define XRG_cpuShowUptime @"cpuShowUptime"

#define XRG_showMemoryPagingGraph @"showMemoryPagingGraph"
#define XRG_memoryShowWired @"memoryShowWired"
#define XRG_memoryShowActive @"memoryShowActive"
#define XRG_memoryShowInactive @"memoryShowInactive"
#define XRG_memoryShowFree @"memoryShowFree"
#define XRG_memoryShowCache @"memoryShowCache"
#define XRG_memoryShowPage @"memoryShowPage"

#define XRG_tempUnits @"tempUnits"
#define XRG_tempFG1Location @"tempFG1Location"
#define XRG_tempFG2Location @"tempFG2Location"
#define XRG_tempFG3Location @"tempFG3Location"
#define XRG_tempFanSpeed @"tempFanSpeed"
#define XRG_tempShowUnknownSensors @"tempShowUnknownSensors"

#define XRG_netMinGraphScale @"netMinGraphScale"
#define XRG_netGraphMode @"netGraphMode"
#define XRG_showTotalBandwidthSinceBoot @"showTotalBandwidthSinceBoot"
#define XRG_showTotalBandwidthSinceLoad @"showTotalBandwidthSinceLoad"
#define XRG_networkInterface @"networkInterface"

#define XRG_diskGraphMode @"diskGraphMode"

#define XRG_ICAO @"icao"
#define XRG_secondaryWeatherGraph @"secondaryWeatherGraph"
#define XRG_temperatureUnits @"temperatureUnits"
#define XRG_distanceUnits @"distanceUnits"
#define XRG_pressureUnits @"pressureUnits"

#define XRG_stockSymbols @"stockSymbols"
#define XRG_stockGraphTimeFrame @"stockGraphTimeFrame"
#define XRG_stockShowChange @"stockShowChange"
#define XRG_showDJIA @"showDJIA"

#define XRG_showCPUGraph @"showCPUGraph"
#define XRG_showGPUGraph @"showGPUGraph"
#define XRG_showNetworkGraph @"showNetworkGraph"
#define XRG_showDiskGraph @"showDiskGraph"
#define XRG_showMemoryGraph @"showMemoryGraph"
#define XRG_showWeatherGraph @"showWeatherGraph"
#define XRG_showStockGraph @"showStockGraph"
#define XRG_showBatteryGraph @"showBatteryGraph"
#define XRG_showTemperatureGraph @"showTemperatureGraph"

#define XRG_CPUOrder @"CPUOrder"
#define XRG_NetworkOrder @"NetworkOrder"
#define XRG_DiskOrder @"DiskOrder"
#define XRG_MemoryOrder @"MemoryOrder"
#define XRG_WeatherOrder @"WeatherOrder"
#define XRG_StockOrder @"StockOrder"
#define XRG_BatteryOrder @"BatteryOrder"

#define XRG_CPU 1
#define XRG_MEMORY 2
#define XRG_BATTERY 3
#define XRG_NET 4
#define XRG_DISK 5
#define XRG_WEATHER 6

#define FLOAT(x) [NSNumber numberWithFloat:x]

#define N1 0.
#define NNE 22.5
#define NE 45.
#define ENE 67.5
#define E 90.
#define ESE 112.5
#define SE 135.
#define SSE 157.5
#define S 180.
#define SSW 202.5
#define SW 225.
#define WSW 247.5
#define W 270.
#define WNW 292.5
#define NW 315.
#define NNW 337.5
#define N2 360.

#endif
