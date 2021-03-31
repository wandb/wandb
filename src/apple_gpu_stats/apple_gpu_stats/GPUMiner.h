//
//  GraphicsMiner.h
//

#import <Foundation/Foundation.h>
#import "DataSet.h"

typedef NS_ENUM(UInt32, PCIVendor) {
    PCIVendorIntel = 0x8086,
    PCIVendorAMD = 0x1002,
    PCIVendorNVidia = 0x10de,
    PCIVendorApple = 0x106b
};

@interface GPUMiner : NSObject

/// Represents the number of samples in each DataSet object.
@property NSInteger numSamples;

/// Represents the number of DataSet objects in each of the following arrays.
@property(nonatomic) NSInteger numberOfGPUs;

/// Values are DataSet objects representing total memory for each GPU.
@property(readonly) NSArray *totalVRAMDataSets;
/// Values are DataSet objects representing free memory for each GPU.
@property(readonly) NSArray *freeVRAMDataSets;
/// Values are DataSet objects representing the CPU wait time for the GPU (units: nanoseconds).
@property(readonly) NSArray *cpuWaitDataSets;
/// Values are DataSet objects representing the device utilization for the GPU (units: %)
@property(readonly) NSArray *utilizationDataSets;
/// Values are NSString objects representing vendor names.
@property(readonly) NSArray *vendorNames;

- (void)getLatestGraphicsInfo;
- (void)setDataSize:(NSInteger)newNumSamples;

@end

@interface GraphicsCard : NSObject

// The PCI vendor id for this card.
@property PCIVendor vendor;

/// The total memory of the GPU in bytes.
@property long long totalVRAM;
/// The used memory of the GPU in bytes.
@property long long usedVRAM;
/// The free memory of the GPU in bytes.
@property long long freeVRAM;
/// The time in nanosecods the CPU waits for the GPU.
@property long long cpuWait;
/// The device utilization in %.
@property int deviceUtilization;

/// Returns YES if the PCI device matches the accelerator.  To test for a match, we detect the PCI device ID (if present) and the PCI vendor ID from the pciDictionary and make sure that the combined value is present in the IOPCIMatch key of the accelerator dictionary.
+ (BOOL)matchingPCIDevice:(NSDictionary *)pciDictionary accelerator:(NSDictionary *)acceleratorDictionary;

/// Initializes the properties using the given PCI dictionary and accelerator.  It is assumed that the client has checked for a match with matchingPCIDevice:accelerator: previously.
- (instancetype)initWithPCIDevice:(NSDictionary *)pciDictionary accelerator:(NSDictionary *)acceleratorDictionary;

/// Returns a string representing the vendor of the GPU.
- (NSString *)vendorString;

@end