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

        // TODO: add M3 GPU temperature

        // GPU / Neural Engine Total Power
        let gpuPower = SMC.shared.getValue("PMVR")

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
        GPUStats["gpuPower"] = gpuPower ?? 0
        GPUStats["systemPower"] = systemPower ?? 0
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
