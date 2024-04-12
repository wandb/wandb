import Foundation

public func getGPUStats() -> [String: Any] {
    var GPUStats: [String: Any] = [:]
    // TODO: this assumes that there is at most only one GPU
    if let gpus = SystemKit.shared.device.info.gpu {
        for gpu in gpus {
            GPUStats["name"] = gpu.name ?? "Unknown"
            GPUStats["vendor"] = gpu.vendor ?? "Unknown"
            GPUStats["vram"] = gpu.vram ?? "Unknown"
            GPUStats["cores"] = gpu.cores ?? 0
        }
    } else {
        return [:]
    }

    guard let accelerators = fetchIOService(kIOAcceleratorClassName) else {
        return [:]
    }
    for (_, accelerator) in accelerators.enumerated() {
        guard let stats = accelerator["PerformanceStatistics"] as? [String: Any] else {
            // print("PerformanceStatistics not found")
            return [:]
        }

        let utilization: Int? = stats["Device Utilization %"] as? Int ?? stats["GPU Activity(%)"] as? Int ?? nil
        let renderUtilization: Int? = stats["Renderer Utilization %"] as? Int ?? nil
        let tilerUtilization: Int? = stats["Tiler Utilization %"] as? Int ?? nil

        let allocatedSystemMemory: Int? = stats["Alloc system memory"] as? Int ?? nil
        let inUseSystemMemory: Int? = stats["In use system memory"] as? Int ?? nil
        let recoveryCount: Int? = stats["recoveryCount"] as? Int ?? nil

        // TODO: Add more stats, such as the CPU, battery temperatures

        // M1 GPU temperature
        // platforms: [.m1, .m1Pro, .m1Max, .m1Ultra]
        let m1Gpu1 = SMC.shared.getValue("Tg05")
        let m1Gpu2 = SMC.shared.getValue("Tg0D")
        let m1Gpu3 = SMC.shared.getValue("Tg0L")
        let m1Gpu4 = SMC.shared.getValue("Tg0T")

        // M2 GPU temperature
        // [.m2, .m2Max, .m2Pro, .m2Ultra]
        let m2Gpu1 = SMC.shared.getValue("Tg0f")
        let m2Gpu2 = SMC.shared.getValue("Tg0j")

        // M3 GPU temperature
        // platforms: [.m3, .m3Pro, .m3Max, .m3Ultra]
        let m3Gpu1 = SMC.shared.getValue("Tf14")
        let m3Gpu2 = SMC.shared.getValue("Tf18")
        let m3Gpu3 = SMC.shared.getValue("Tf19")
        let m3Gpu4 = SMC.shared.getValue("Tf1A")
        let m3Gpu5 = SMC.shared.getValue("Tf24")
        let m3Gpu6 = SMC.shared.getValue("Tf28")
        let m3Gpu7 = SMC.shared.getValue("Tf29")
        let m3Gpu8 = SMC.shared.getValue("Tf2A")

        // TODO: add M3 GPU temperature

        // GPU / Neural Engine Total Power
        let gpuPowerPMVR = SMC.shared.getValue("PMVR")
        let gpuPowerPGTR = SMC.shared.getValue("PGTR")
        let gpuPowerPG0R = SMC.shared.getValue("PG0R")

        let gpuVoltage = SMC.shared.getValue("VG0C")
        let gpuCurrent = SMC.shared.getValue("IG0C")
        let gpuPower = SMC.shared.getValue("PG0C")

        let PC10 = SMC.shared.getValue("PC10")
        let PC12 = SMC.shared.getValue("PC12")
        let PC20 = SMC.shared.getValue("PC20")
        let PC22 = SMC.shared.getValue("PC22")
        let PC40 = SMC.shared.getValue("PC40")

        // System total power
        let systemPower = SMC.shared.getValue("PSTR")

        GPUStats["utilization"] = utilization ?? 0
        GPUStats["renderUtilization"] = renderUtilization ?? 0
        GPUStats["tilerUtilization"] = tilerUtilization ?? 0
        GPUStats["allocatedSystemMemory"] = allocatedSystemMemory ?? 0
        GPUStats["inUseSystemMemory"] = inUseSystemMemory ?? 0
        GPUStats["recoveryCount"] = recoveryCount ?? 0
        GPUStats["m1Gpu1"] = m1Gpu1 ?? 0
        GPUStats["m1Gpu2"] = m1Gpu2 ?? 0
        GPUStats["m1Gpu3"] = m1Gpu3 ?? 0
        GPUStats["m1Gpu4"] = m1Gpu4 ?? 0
        GPUStats["m2Gpu1"] = m2Gpu1 ?? 0
        GPUStats["m2Gpu2"] = m2Gpu2 ?? 0
        GPUStats["m3Gpu1"] = m3Gpu1 ?? 0
        GPUStats["m3Gpu2"] = m3Gpu2 ?? 0
        GPUStats["m3Gpu3"] = m3Gpu3 ?? 0
        GPUStats["m3Gpu4"] = m3Gpu4 ?? 0
        GPUStats["m3Gpu5"] = m3Gpu5 ?? 0
        GPUStats["m3Gpu6"] = m3Gpu6 ?? 0
        GPUStats["m3Gpu7"] = m3Gpu7 ?? 0
        GPUStats["m3Gpu8"] = m3Gpu8 ?? 0
        GPUStats["gpuPowerPMVR"] = gpuPowerPMVR ?? 0
        GPUStats["gpuPowerPGTR"] = gpuPowerPGTR ?? 0
        GPUStats["gpuPowerPG0R"] = gpuPowerPG0R ?? 0
        GPUStats["gpuVoltage"] = gpuVoltage ?? 0
        GPUStats["gpuCurrent"] = gpuCurrent ?? 0
        GPUStats["gpuPower"] = gpuPower ?? 0
        GPUStats["systemPower"] = systemPower ?? 0

        GPUStats["PC10"] = PC10 ?? 0
        GPUStats["PC12"] = PC12 ?? 0
        GPUStats["PC20"] = PC20 ?? 0
        GPUStats["PC22"] = PC22 ?? 0
        GPUStats["PC40"] = PC40 ?? 0
    }

    return GPUStats
}

public func gpuStats() {
    let stats: [String: Any] = getGPUStats()

    do {
        let jsonData = try JSONSerialization.data(withJSONObject: stats, options: [])
        if let jsonString = String(data: jsonData, encoding: .utf8) {
            print(jsonString)
        }
    } catch {
        print("Error serializing stats: \(error)")
    }
}

gpuStats()
