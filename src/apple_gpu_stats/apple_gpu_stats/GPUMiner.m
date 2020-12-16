//
//  GraphicsMiner.m
//

#import "GPUMiner.h"
#import <IOKit/graphics/IOGraphicsLib.h>

@implementation GPUMiner

- (instancetype)init {
	self = [super init];
	if (self) {
		_totalVRAMDataSets = nil;
		_freeVRAMDataSets = nil;
		_cpuWaitDataSets = nil;
		self.numSamples = 0;
		self.numberOfGPUs = 0;
		
		[self setNumberOfGPUs:1];
		[self getLatestGraphicsInfo];
	}
	
	return self;
}


- (void)setDataSize:(NSInteger)newNumSamples {
	if (newNumSamples < 0) return;
	
	for (DataSet *values in self.totalVRAMDataSets) {
		[values resize:newNumSamples];
	}
	for (DataSet *values in self.freeVRAMDataSets) {
		[values resize:newNumSamples];
	}
	for (DataSet *values in self.cpuWaitDataSets) {
		[values resize:newNumSamples];
	}
    for (DataSet *values in self.utilizationDataSets) {
        [values resize:newNumSamples];
    }
	
	self.numSamples = newNumSamples;
}

- (void)setNumberOfGPUs:(NSInteger)newNumGPUs {
	if ((self.totalVRAMDataSets.count == newNumGPUs) &&
		(self.freeVRAMDataSets.count == newNumGPUs) &&
		(self.cpuWaitDataSets.count == newNumGPUs) &&
        (self.utilizationDataSets.count == newNumGPUs))
	{
		return;
	}
	
	NSMutableArray *newTotal = [NSMutableArray array];
	NSMutableArray *newFree = [NSMutableArray array];
	NSMutableArray *newCPUWait = [NSMutableArray array];
    NSMutableArray *newUtilization = [NSMutableArray array];
	
	if (self.totalVRAMDataSets.count) [newTotal addObjectsFromArray:self.totalVRAMDataSets];
	if (self.freeVRAMDataSets.count) [newFree addObjectsFromArray:self.freeVRAMDataSets];
	if (self.cpuWaitDataSets.count) [newCPUWait addObjectsFromArray:self.cpuWaitDataSets];
    if (self.utilizationDataSets.count) [newUtilization addObjectsFromArray:self.utilizationDataSets];
	
	// Make sure we want at least 1 sample.
	self.numSamples = MAX(1, self.numSamples);
	
	// Add new DataSets if needed.
	for (NSInteger i = 0; i < newNumGPUs; i++) {
		if (newTotal.count <= i) {
			DataSet *s = [[DataSet alloc] init];
			[s resize:self.numSamples];
			[newTotal addObject:s];
		}
		if (newFree.count <= i) {
			DataSet *s = [[DataSet alloc] init];
			[s resize:self.numSamples];
			[newFree addObject:s];
		}
		if (newCPUWait.count <= i) {
			DataSet *s = [[DataSet alloc] init];
			[s resize:self.numSamples];
			[newCPUWait addObject:s];
		}
        if (newUtilization.count <= i) {
            DataSet *s = [[DataSet alloc] init];
            [s resize:self.numSamples];
            [newUtilization addObject:s];
        }
	}

	// Remove extra DataSets if needed.
	if (newTotal.count > newNumGPUs) {
		newTotal = [NSMutableArray arrayWithArray:[newTotal subarrayWithRange:NSMakeRange(0, newNumGPUs)]];
	}
	if (newFree.count > newNumGPUs) {
		newFree = [NSMutableArray arrayWithArray:[newFree subarrayWithRange:NSMakeRange(0, newNumGPUs)]];
	}
	if (newCPUWait.count > newNumGPUs) {
		newCPUWait = [NSMutableArray arrayWithArray:[newCPUWait subarrayWithRange:NSMakeRange(0, newNumGPUs)]];
	}
    if (newUtilization.count > newNumGPUs) {
        newUtilization = [NSMutableArray arrayWithArray:[newUtilization subarrayWithRange:NSMakeRange(0, newNumGPUs)]];
    }
	
	_totalVRAMDataSets = newTotal;
	_freeVRAMDataSets = newFree;
	_cpuWaitDataSets = newCPUWait;
    _utilizationDataSets = newUtilization;
	
	self.numberOfGPUs = newNumGPUs;
}

- (void)getLatestGraphicsInfo {
	// Create an iterator
	io_iterator_t iterator;
	
	NSMutableArray *accelerators = [NSMutableArray array];
	NSMutableArray *pciDevices = [NSMutableArray array];
	
	if (IOServiceGetMatchingServices(kIOMasterPortDefault, IOServiceMatching(kIOAcceleratorClassName), &iterator) == kIOReturnSuccess) {
		// Iterator for devices found
		io_registry_entry_t regEntry;
		
		while ((regEntry = IOIteratorNext(iterator))) {
			// Put this services object into a dictionary object.
			CFMutableDictionaryRef serviceDictionary;
			if (IORegistryEntryCreateCFProperties(regEntry, &serviceDictionary, kCFAllocatorDefault, kNilOptions) != kIOReturnSuccess) {
				// Service dictionary creation failed.
				IOObjectRelease(regEntry);
				continue;
			}
			
			[accelerators addObject:[(__bridge NSDictionary *)serviceDictionary copy]];
			
			CFRelease(serviceDictionary);
			IOObjectRelease(regEntry);
		}
		IOObjectRelease(iterator);
	}
	
	if (IOServiceGetMatchingServices(kIOMasterPortDefault, IOServiceMatching("IOPCIDevice"), &iterator) == kIOReturnSuccess) {
		io_registry_entry_t serviceObject;
		while ((serviceObject = IOIteratorNext(iterator))) {
			// Put this services object into a CF Dictionary object.
			CFMutableDictionaryRef serviceDictionary;
			if (IORegistryEntryCreateCFProperties(serviceObject, &serviceDictionary, kCFAllocatorDefault, kNilOptions) != kIOReturnSuccess) {
				IOObjectRelease(serviceObject);
				continue;
			}
			
			// Check if this is a GPU listing.
			const void *model = CFDictionaryGetValue(serviceDictionary, @"model");
			if (model != nil) {
				if (CFGetTypeID(model) == CFDataGetTypeID()) {
					[pciDevices addObject:[(__bridge NSDictionary *)serviceDictionary copy]];
				}
			}
			
			CFRelease(serviceDictionary);
			IOObjectRelease(serviceObject);
		}
		
		IOObjectRelease(iterator);
	}
	
	NSInteger numValues = MIN(pciDevices.count, accelerators.count);

	NSMutableArray *graphicsCards = [NSMutableArray array];		// An array of GraphicsCard objects.
	NSMutableIndexSet *pciIndicesUsed = [[NSMutableIndexSet alloc] init];
	NSMutableIndexSet *accelIndicesUsed = [[NSMutableIndexSet alloc] init];
	for (NSInteger i = 0; i < numValues; i++) {
		// Most of the time, pciDevices[i] will match accelerators[i].  But sometimes this isn't the case.
		// Try to detect if this is happening and compensate for it.
		NSDictionary *pciD = pciDevices[i];
		NSDictionary *accelD = accelerators[i];
		if ([GraphicsCard matchingPCIDevice:pciD accelerator:accelD]) {
			// Matched.  Let's go with it.
			GraphicsCard *card = [[GraphicsCard alloc] initWithPCIDevice:pciD accelerator:accelD];
			if (card) [graphicsCards addObject:card];
			[pciIndicesUsed addIndex:i];
			[accelIndicesUsed addIndex:i];
		}
		else {
			// Mismatch was detected.  Try finding a different accelerator dictionary that does match the current pci dictionary.
			for (NSInteger j = 0; j < accelerators.count; j++) {
				if ([accelIndicesUsed containsIndex:j]) continue;
				
				if ([GraphicsCard matchingPCIDevice:pciD accelerator:accelerators[j]]) {
					// Found a match.
					GraphicsCard *card = [[GraphicsCard alloc] initWithPCIDevice:pciD accelerator:accelerators[j]];
					if (card) [graphicsCards addObject:card];
					[pciIndicesUsed addIndex:i];
					[accelIndicesUsed addIndex:j];
					break;
				}
			}
			
			// It's possible to fall out of this loop without finding a matching accelerator for the pci device.
		}
	}
	
	// If we couldn't match the graphics cards using the method above, just match all remaining cards in the order they were detected.
    if (pciDevices.count > 0) {
        for (NSInteger i = 0; i < pciDevices.count; i++) {
            if ([pciIndicesUsed containsIndex:i]) continue;
            
            for (NSInteger j = 0; j < accelerators.count; j++) {
                if ([accelIndicesUsed containsIndex:j]) continue;
                
                // Match these devices.
                GraphicsCard *card = [[GraphicsCard alloc] initWithPCIDevice:pciDevices[i] accelerator:accelerators[j]];
                if (card) [graphicsCards addObject:card];
                [pciIndicesUsed addIndex:i];
                [accelIndicesUsed addIndex:j];
            }
        }
    }
    else {
        // On Apple silicon devices, there won't be a separate PCI device for the GPU because it's embedded on the SoC.
        for (NSInteger i = 0; i < accelerators.count; i++) {
            if ([accelIndicesUsed containsIndex:i]) continue;
            
            GraphicsCard *card = [[GraphicsCard alloc] initWithPCIDevice:nil accelerator:accelerators[i]];
            if (card) [graphicsCards addObject:card];
            [accelIndicesUsed addIndex:i];
        }
    }
    
	// Now that we've parsed all the data, set the next values for our data sets.
	NSMutableArray *updatedVendors = [NSMutableArray array];
	[self setNumberOfGPUs:graphicsCards.count];
	for (NSInteger i = 0; i < graphicsCards.count; i++) {
		[self.totalVRAMDataSets[i] setNextValue:[graphicsCards[i] totalVRAM]];
		[self.freeVRAMDataSets[i] setNextValue:[graphicsCards[i] freeVRAM]];
		[self.cpuWaitDataSets[i] setNextValue:[graphicsCards[i] cpuWait]];
        [self.utilizationDataSets[i] setNextValue:[graphicsCards[i] deviceUtilization]];
		
		NSString *vendorName = [graphicsCards[i] vendorString];
		if (!vendorName) vendorName = @"";
		[updatedVendors addObject:vendorName];
	}
	_vendorNames = updatedVendors;
}

@end

@implementation GraphicsCard

+ (BOOL)matchingPCIDevice:(NSDictionary *)pciDictionary accelerator:(NSDictionary *)acceleratorDictionary {
	id pciVendor = pciDictionary[@"vendor-id"];
	UInt32 pciVendorInt = 0xFFFF;
	if ([pciVendor isKindOfClass:[NSData class]]) {
		NSData *pciVendorData = pciVendor;
		if (pciVendorData.length >= 4) {
			UInt32 *vendorInt = (UInt32 *)pciVendorData.bytes;
			pciVendorInt = *vendorInt;
		}
	}
	id pciDevice = pciDictionary[@"device-id"];
	UInt32 pciDeviceInt = 0xFFFF;
	if ([pciDevice isKindOfClass:[NSData class]]) {
		NSData *pciDeviceData = pciDevice;
		if (pciDeviceData.length >= 4) {
			UInt32 *deviceInt = (UInt32 *)pciDeviceData.bytes;
			pciDeviceInt = *deviceInt;
		}
	}
	
	if (pciVendorInt != 0xFFFF) {
		id pciMatch = [acceleratorDictionary[@"IOPCIMatch"] uppercaseString];
		if (!pciMatch) pciMatch = [acceleratorDictionary[@"IOPCIPrimaryMatch"] uppercaseString];

		if (pciDeviceInt != 0xFFFF) {
			// We have a vendor and a device.  Check both.
			UInt32 pciComboInt = (pciDeviceInt << 16) | pciVendorInt;
			NSString *checkString = [[NSString stringWithFormat:@"%x", pciComboInt] uppercaseString];
			if ([pciMatch rangeOfString:checkString].location != NSNotFound) {
				return YES;
			}
		}
		else {
			// Only have a vendor, check what we can.
			NSString *checkString = [[NSString stringWithFormat:@"%x", pciVendorInt] uppercaseString];
			NSString *checkStringWithSpace = [checkString stringByAppendingString:@" "];
			if (([pciMatch rangeOfString:checkStringWithSpace].location != NSNotFound) || [pciMatch hasSuffix:checkString]) {
				return YES;
			}
		}
	}
	
	return NO;
}

- (instancetype)initWithPCIDevice:(NSDictionary *)pciDictionary accelerator:(NSDictionary *)acceleratorDictionary {
	if (self = [super init]) {
		// Vendor.
		id pciVendor = pciDictionary[@"vendor-id"];
        id accelVendor = acceleratorDictionary[@"vendor-id"];
		if ([pciVendor isKindOfClass:[NSData class]]) {
			NSData *pciVendorData = pciVendor;
			if (pciVendorData.length >= 4) {
				UInt32 *vendorInt = (UInt32 *)pciVendorData.bytes;
				self.vendor = *vendorInt;
			}
		}
        else if ([accelVendor isKindOfClass:[NSData class]]) {
            NSData *accelVendorData = accelVendor;
            if (accelVendorData.length >= 4) {
                UInt32 *vendorInt = (UInt32 *)accelVendorData.bytes;
                self.vendor = *vendorInt;
            }
        }

		// The VRAM and other stats gathered.
		// Not all VRAM stats will be populated from the GPU data.
		// We'll hope for 2 out of 3 so the third can be calculated.

		id vramTotal = acceleratorDictionary[@"VRAM,totalMB"];
		if ([vramTotal isKindOfClass:[NSNumber class]]) {
			self.totalVRAM = [vramTotal longLongValue] * 1024ll * 1024ll;
		}
		else {
			vramTotal = pciDictionary[@"VRAM,totalMB"];
			if ([vramTotal isKindOfClass:[NSNumber class]]) {
				self.totalVRAM = [vramTotal longLongValue] * 1024ll * 1024ll;
			}
			else {
				vramTotal = pciDictionary[@"ATY,memsize"];
				if ([vramTotal isKindOfClass:[NSNumber class]]) {
					self.totalVRAM = [vramTotal longLongValue];
				}
				else {
					self.totalVRAM = -1;
				}
			}
		}
		
		id perf_properties = acceleratorDictionary[@"PerformanceStatistics"];
		if ([perf_properties isKindOfClass:[NSDictionary class]]) {
			NSDictionary *perf = (NSDictionary *)perf_properties;
            			
			id freeVram = perf[@"vramFreeBytes"];
			id usedVram = perf[@"vramUsedBytes"];
			id cpuWait = perf[@"hardwareWaitTime"];
            id appleUtilization = perf[@"Device Utilization %"];
			
			self.freeVRAM = [freeVram isKindOfClass:[NSNumber class]] ? [freeVram longLongValue] : -1;
			self.usedVRAM = [usedVram isKindOfClass:[NSNumber class]] ? [usedVram longLongValue] : -1;
			self.cpuWait = [cpuWait isKindOfClass:[NSNumber class]] ? [cpuWait longLongValue] : 0;
            self.deviceUtilization = [appleUtilization isKindOfClass:[NSNumber class]] ? [appleUtilization intValue] : 0;
			
			if (((self.usedVRAM <= 0) || (self.usedVRAM > self.totalVRAM)) && ((self.freeVRAM <= 0) || (self.freeVRAM > self.totalVRAM))) {
				usedVram = perf[@"inUseVidMemoryBytes"];
				self.usedVRAM = [usedVram isKindOfClass:[NSNumber class]] ? [usedVram longLongValue] : -1;
				self.freeVRAM = -1;
			}
            
            if (self.usedVRAM == -1) {
                id appleUsedVram = perf[@"In use system memory"];
                self.usedVRAM = [appleUsedVram isKindOfClass:[NSNumber class]] ? [appleUsedVram longLongValue] : -1;
            }
            if (self.totalVRAM == -1) {
                id appleTotalVram = perf[@"Alloc system memory"];
                self.totalVRAM = [appleTotalVram isKindOfClass:[NSNumber class]] ? [appleTotalVram longLongValue] : -1;
            }
		}

		// Do a check for our VRAM values.
		BOOL okay = [self valuesOkay];
		
		if (!okay) {
			// If we get here, then we can't get VRAM in a reliable way.  However, there is always the GART method.
			// This doesn't work on all cards (especially those with more than 2GB of VRAM), but the cards this won't work well on will probably be caught above.
			if ([perf_properties isKindOfClass:[NSDictionary class]]) {
				NSDictionary *perf = (NSDictionary *)perf_properties;
				
				id freeVram = perf[@"gartFreeBytes"];
				id usedVram = perf[@"gartUsedBytes"];
				id totalVram = perf[@"gartSizeBytes"];
				
				self.freeVRAM = [freeVram isKindOfClass:[NSNumber class]] ? [freeVram longLongValue] : -1;
				self.usedVRAM = [usedVram isKindOfClass:[NSNumber class]] ? [usedVram longLongValue] : -1;
				self.totalVRAM = [totalVram isKindOfClass:[NSNumber class]] ? [totalVram longLongValue] : -1;
			}
			
			okay = [self valuesOkay];
		}
		
		if (!okay) {
			self.totalVRAM = 0;
			self.freeVRAM = 0;
			self.usedVRAM = 0;
		}
	}

	return self;
}

- (BOOL)valuesOkay {
	BOOL okay = NO;
	if ((self.totalVRAM == -1) && (self.usedVRAM != -1) && (self.freeVRAM != -1)) {
		self.totalVRAM = self.usedVRAM + self.freeVRAM;
		okay = YES;
	}
	else if ((self.totalVRAM != -1) && (self.usedVRAM == -1) && (self.freeVRAM != -1)) {
		if (self.freeVRAM == 0) {
			self.usedVRAM = 0;		// Our one exception, free being 0 is more often missing data instead of really being the case.
			self.freeVRAM = self.totalVRAM - self.usedVRAM;
			okay = NO;
		}
		else {
			self.usedVRAM = self.totalVRAM - self.freeVRAM;
			okay = YES;
		}
	}
	else if ((self.totalVRAM != -1) && (self.usedVRAM != -1) && (self.freeVRAM == -1)) {
        if (self.usedVRAM == 0) {
            self.freeVRAM = self.totalVRAM;		// Our one exception, used being 0 is more often missing data instead of really being the case.
            okay = NO;
        }
        else {
            self.freeVRAM = self.totalVRAM - self.usedVRAM;
            okay = YES;
        }
	}
	else if ((self.totalVRAM != -1) && (self.usedVRAM != -1) && (self.freeVRAM != -1)) {
		okay = YES;
	}
	else {
		// Couldn't get data for this GPU.
		okay = NO;
	}
	
	if (self.usedVRAM > self.totalVRAM) {
		okay = NO;
	}
	if (self.usedVRAM < 0) {
		okay = NO;
	}
	
	return okay;
}

- (NSString *)vendorString {
	if (self.vendor == PCIVendorAMD) {
		return @"AMD";
	}
	else if (self.vendor == PCIVendorNVidia) {
		return @"nVidia";
	}
	else if (self.vendor == PCIVendorIntel) {
		return @"Intel";
	}
    else if (self.vendor == PCIVendorApple) {
        return @"Apple";
    }
	else {
		return nil;
	}
}

@end
