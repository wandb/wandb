//
//  main.m
//  apple_gpu_stats
//
//  Created by Chris Van Pelt on 12/5/20.
//


#import <Foundation/Foundation.h>
#import "GPUMiner.h"
#import "TemperatureMiner.h"

static void NSPrint(NSString *format, ...)
 {
    va_list args;
    
    va_start(args, format);
    NSString *string  = [[NSString alloc] initWithFormat:format arguments:args];
    va_end(args);
    
    fprintf(stdout, "%s\n", [string UTF8String]);
    
#if !__has_feature(objc_arc)
    [string release];
#endif
}

int main(int argc, const char * argv[]) {
    GPUMiner *graphicsMiner;
    TemperatureMiner *tempMiner;
    graphicsMiner = [[GPUMiner alloc] init];
    tempMiner = [[TemperatureMiner alloc] init];
    NSArray *utilizationValues = [graphicsMiner utilizationDataSets];
    NSArray *cpuWaitValues = [graphicsMiner cpuWaitDataSets];
    NSArray *totalValues = [graphicsMiner totalVRAMDataSets];
    NSArray *freeValues = [graphicsMiner freeVRAMDataSets];
    if(argc == 1) {
        NSPrint(@"Name\tUtilization\tCPU Wait\tMemory Used (%%)\tMemory Used (MB)\tPower (watts)\tTemperature (Celcius)");
    }

    [graphicsMiner getLatestGraphicsInfo];
    [tempMiner setDisplayFans:YES];
    [tempMiner setCurrentTemperatures];
    
    float temperature = 0;
    float power = 0;

    NSArray *locations = [tempMiner locationKeysInOrder];
    for (NSInteger i = 0; i < [locations count]; i++) {
        NSString *primaryLabel = [tempMiner labelForKey:locations[i]];
        float primaryValue = [tempMiner currentValueForKey:locations[i]];
        if(temperature == 0 && [primaryLabel isEqualToString:@"Neural Engine"]) {
            temperature = primaryValue;
        } else if(temperature == 0 && [primaryLabel isEqualToString:@"CPU Proximity"]) {
            temperature = primaryValue;
        } else {
            // NSLog(@"Other: %@ - %f", primaryLabel, primaryValue);
        }
        if([primaryLabel isEqualToString:@"GPU / Neural Engine Total"]) {
            power = primaryValue;
        } else if(power == 0 && [primaryLabel isEqualToString:@"GPU Rail Power"]) {
            power = primaryValue;
        } else if(power == 0 && [primaryLabel isEqualToString:@"System Total Power"]) {
            power = primaryValue;
        }
    }

    for (NSInteger i = 0; i < totalValues.count; i++) {
        NSString *vendorString = graphicsMiner.vendorNames[i];
        NSString *paddedVendor = [NSString stringWithFormat:@"%@%*s", vendorString, (int)(6-vendorString.length), ""];
        CGFloat u = [utilizationValues[i] currentValue];
        CGFloat t = [totalValues[i] currentValue];
        CGFloat c = [cpuWaitValues[i] currentValue];
        CGFloat f = [freeValues[i] currentValue];
            
        CGFloat memoryUsedMB = (t - f) / 1024. / 1024.;
        CGFloat percentUsed = (t - f) / t * 100.;
        NSString *waitTime = nil;

        waitTime = [NSString stringWithFormat:@"%d µs", (int)(c / 1000)];
        
        if(argc > 1) {
            NSPrint(@"{\"vendor\":\"%@\", \"utilization\":%f, \"cpu_wait_ms\":%f, \"mem_used\": %f, \"temperature\": %f, \"power\": %f}", paddedVendor,u,c/1000000,percentUsed,temperature, power);
        } else {
            NSPrint(@"%@\t%.3f%%\t\t%@\t%.3f%%\t%dM\t%.3fW\t%.3fC",paddedVendor,u,waitTime,percentUsed,(int)round(memoryUsedMB),power,temperature);
        }
    }
}
