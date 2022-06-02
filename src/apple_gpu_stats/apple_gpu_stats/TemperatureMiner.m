#import "TemperatureMiner.h"
#import "SMCSensors.h"
#import "definitions.h"

#import <mach/mach_host.h>
#import <mach/mach_port.h>
#import <mach/vm_map.h>

#undef DEBUG

@implementation TemperatureMiner
- (instancetype)init {
	self = [super init];
	
	if (self) {
		host = mach_host_self();
		
		unsigned int count = HOST_BASIC_INFO_COUNT;
		host_basic_info_data_t info;
		host_info(host, HOST_BASIC_INFO, (host_info_t)&info, &count);
		
		// Set the number of CPUs
		numCPUs = [self numberOfCPUs];
		
		displayFans = YES;
		fanLocations = [NSMutableDictionary dictionary];
		locationKeysInOrder = [NSMutableArray array];
		sensorData = [NSMutableDictionary dictionary];
		smcSensors = [[SMCSensors alloc] init];
	}

    return self;
}

- (void)reset {
    for (NSDictionary *sensorValue in [sensorData allValues]) {
        [sensorValue[GSDataSetKey] reset];
    }
}

- (int)numberOfCPUs {
    processor_cpu_load_info_t		newCPUInfo;
    kern_return_t					kr;
    unsigned int					processor_count;
    mach_msg_type_number_t			load_count;

    kr = host_processor_info(host, 
                             PROCESSOR_CPU_LOAD_INFO, 
                             &processor_count, 
                             (processor_info_array_t *)&newCPUInfo, 
                             &load_count);
    if (kr != KERN_SUCCESS) {
        return 0;
    }
    else {
        vm_deallocate(mach_task_self(), (vm_address_t)newCPUInfo, (vm_size_t)(load_count * sizeof(*newCPUInfo)));
        return (int)processor_count;
    }
}

- (void)setCurrentTemperatures {
    // Only refresh the temperature every 5 seconds.
    temperatureCounter = (temperatureCounter + 1) % 5;
    if (temperatureCounter != 1) {
        return;
    }
    
	// Set each temperature sensor enable bit to NO.
	NSEnumerator *enumerator = [sensorData objectEnumerator];
	id value;
	while (value = [enumerator nextObject]) {
		value[GSEnable] = @"NO";
	}
    	
	// Intel: use SMC
	@try {
		[self trySMCTemperature];
    } @catch (NSException *e) { }
		
	// Before returning, go through the values and find the ones that aren't enabled.
	enumerator = [sensorData objectEnumerator];
	while (value = [enumerator nextObject]) {
		if ([value[GSEnable] boolValue] == NO) {
			[value[GSDataSetKey] setNextValue:0];
			value[GSCurrentValueKey] = @0;
		}
	}
}

- (void) trySMCTemperature {
	id key;
	int i;

	NSDictionary *values = [smcSensors temperatureValuesExtended:YES];
	//NSLog(@"values: %@", values);
	NSEnumerator *keyEnum = [values keyEnumerator];
	
	while( nil != (key = [keyEnum nextObject]) )
	{
		id aValue = values[key];
		if (![aValue isKindOfClass:[NSNumber class]]) continue;		// Fix TE..
        
		float temperature = [aValue floatValue];
		// Throw out temperatures that are too high to be reasonable.
		if (temperature > 150) {
			continue;
		}
        NSString *humanReadableName = [smcSensors humanReadableNameForKey:key];

		[self setCurrentValue:temperature
					 andUnits:[NSString stringWithFormat:@"%CC", (unsigned short)0x00B0] 
				  forLocation:humanReadableName];
	}
    
    // POWER, to view all power keys set this to YES
    values = [smcSensors powerValuesExtended:NO];
    NSEnumerator *pKeyEnum = [values keyEnumerator];
    
    while( nil != (key = [pKeyEnum nextObject]) )
    {
        id aValue = values[key];
        if (![aValue isKindOfClass:[NSNumber class]]) continue;        // Fix TE..
        
        float watts = [aValue floatValue];
        NSString *humanReadableName = [smcSensors humanReadableNameForKey:key];

        [self setCurrentValue:watts
                     andUnits:[NSString stringWithFormat:@" watts"]
                  forLocation:humanReadableName];
    }
    
	if( displayFans ) {
        values = [smcSensors fanValues];
        NSArray *keys = [values allKeys];
        for (i = 0; i < [keys count]; i++) {
            id fanKey = keys[i];
            NSString *fanLocation = fanKey;
            
            id fanDict = values[fanKey];
			
			// Find the actual fan speed key.
			NSArray *fanDictKeys = [fanDict allKeys];
			NSUInteger speedKeyIndex = [fanDictKeys indexOfObjectPassingTest:^BOOL(id obj, NSUInteger idx, BOOL *stop){
				if ([obj hasSuffix:@"Ac"]) {
					*stop = YES;
					return YES;
				}
				
				return NO;
			}];
			if (speedKeyIndex != NSNotFound) {
				id fanSpeedKey = fanDictKeys[speedKeyIndex];
                if ([fanDict[fanSpeedKey] isKindOfClass:[NSData class]]) {
                    float *speed = (float *)[fanDict[fanSpeedKey] bytes];
                    [self setCurrentValue:*speed
                                 andUnits:@" rpm"
                              forLocation:fanLocation];
                }
                else {
                    [self setCurrentValue:[fanDict[fanSpeedKey] floatValue]
                                 andUnits:@" rpm"
                              forLocation:fanLocation];
                }
			}
        }
    }
	
	return;
}

- (void)setDisplayFans:(bool)yesNo {
	displayFans = yesNo;
	
	if (displayFans == NO) {
		NSArray *fanLocationKeys = [fanLocations allKeys];
		
		int i;
		for (i = 0; i < [fanLocationKeys count]; i++) {
			NSString *location = fanLocationKeys[i];
			
			[sensorData removeObjectForKey:location];			
		}

		[self regenerateLocationKeyOrder];
	}
}

- (NSArray *)locationKeys {
    return [sensorData allKeys];
}

- (NSArray *)locationKeysInOrder {
    return locationKeysInOrder;
}

- (NSString *)unitsForLocation:(NSString *)location {
	return sensorData[location][GSUnitsKey];
}

- (void)regenerateLocationKeyOrder {
    NSArray        *locations        = [sensorData allKeys];
    NSInteger      numLocations      = [locations count];
    if (numLocations == 0) return;
    
    BOOL alreadyUsed[numLocations];

	[locationKeysInOrder removeAllObjects];

    for (int i = 0; i < numLocations; i++) {
        if (locations[i] == nil) {
            alreadyUsed[i] = YES;
        } else {
            alreadyUsed[i] = NO;
        }
    }
    
	NSMutableArray *types = [NSMutableArray arrayWithObjects:
		[NSString stringWithFormat:@"%CC", (unsigned short)0x00B0], 
		@" rpm",
        @" watts",
		@"%", 
		nil];

	int typeIndex;
	for (typeIndex = 0; typeIndex < [types count]; typeIndex++) {
		NSMutableArray *tmpCPUCore = [NSMutableArray arrayWithCapacity:3];
		NSMutableArray *tmpCPUA    = [NSMutableArray arrayWithCapacity:3];
		NSMutableArray *tmpCPUB    = [NSMutableArray arrayWithCapacity:3];
		NSMutableArray *tmpCPU     = [NSMutableArray arrayWithCapacity:3];
		NSMutableArray *tmpU3      = [NSMutableArray arrayWithCapacity:3];
		NSMutableArray *tmpGPU     = [NSMutableArray arrayWithCapacity:3];
		NSMutableArray *tmpBattery = [NSMutableArray arrayWithCapacity:3];
		NSMutableArray *tmpDrive   = [NSMutableArray arrayWithCapacity:3];
		NSMutableArray *tmpOthers  = [NSMutableArray arrayWithCapacity:3];
		
		for (int i = 0; i < numLocations; i++) {
			if (alreadyUsed[i]) continue;
			
			NSString *location = locations[i];
			if (![sensorData[location][GSUnitsKey] isEqualToString:types[typeIndex]]) {
				continue;
			}

			// Matches CPU and CORE
			NSRange r = [location rangeOfString:@"CPU"];
			if (r.location != NSNotFound) {
				r = [location rangeOfString:@"CORE"];
				if (r.location != NSNotFound) {
					[tmpCPUCore addObject:location];
					alreadyUsed[i] = YES;
					continue;
				}
			}
			
			// Matches CPU A
			r = [location rangeOfString:@"CPU A"];
			if (r.location != NSNotFound) {
				[tmpCPUA addObject:location];
				alreadyUsed[i] = YES;
				continue;
			}
		
			// Matches CPU B
			r = [location rangeOfString:@"CPU B"];
			if (r.location != NSNotFound) {
				[tmpCPUB addObject:location];
				alreadyUsed[i] = YES;
				continue;
			}
		
			// Matches CPU
			r = [location rangeOfString:@"CPU"];
			if (r.location != NSNotFound) {
				[tmpCPU addObject:location];
				alreadyUsed[i] = YES;
				continue;
			}
					
			// Matches U3 (for the memory controller in a G5)
			r = [location rangeOfString:@"U3"];
			if (r.location != NSNotFound) {
				[tmpU3 addObject:location];
				alreadyUsed[i] = YES;
				continue;
			}
			
			// Matches Memory (for Intel SMC)
			r = [location rangeOfString:@"Memory"];
			if (r.location != NSNotFound) {
				[tmpU3 addObject:location];
				alreadyUsed[i] = YES;
				continue;
			}			
		
			// Matches GPU
			r = [location rangeOfString:@"GPU"];
			if (r.location != NSNotFound) {
				[tmpGPU addObject:location];
				alreadyUsed[i] = YES;
				continue;
			}
		
			// Add any that match Battery
			r = [location rangeOfString:@"BATTERY"];
			if (r.location != NSNotFound) {
				[tmpBattery addObject:location];
				alreadyUsed[i] = YES;
				continue;
			}
		
			// Add any that match Drive
			r = [location rangeOfString:@"DRIVE"];
			if (r.location != NSNotFound) {
				[tmpDrive addObject:location];
				alreadyUsed[i] = YES;
				continue;
			}
			
			r = [location rangeOfString:@"HDD"];
			if (r.location != NSNotFound) {
				[tmpDrive addObject:location];
				alreadyUsed[i] = YES;
				continue;
			}
		}
		
		// Loop through and add any left overs
		for (int i = 0; i < numLocations; i++) {
			if ((!alreadyUsed[i]) & [sensorData[locations[i]][GSUnitsKey] isEqualToString:types[typeIndex]]) {
				[tmpOthers addObject:locations[i]];
				alreadyUsed[i] = YES;
			}
		}
		
        NSSortDescriptor *descriptor = [NSSortDescriptor sortDescriptorWithKey:@"self"
                                                                         ascending:YES
                                                                        comparator:^(id obj1, id obj2) {
                                                                            return [obj1 compare:obj2 options:NSNumericSearch];
                                                                        }];
        
		[locationKeysInOrder addObjectsFromArray:[tmpCPUCore sortedArrayUsingDescriptors:@[descriptor]]];
		[locationKeysInOrder addObjectsFromArray:[tmpCPUA sortedArrayUsingDescriptors:@[descriptor]]];
		[locationKeysInOrder addObjectsFromArray:[tmpCPUB sortedArrayUsingDescriptors:@[descriptor]]];
		[locationKeysInOrder addObjectsFromArray:[tmpCPU sortedArrayUsingDescriptors:@[descriptor]]];
		[locationKeysInOrder addObjectsFromArray:[tmpGPU sortedArrayUsingDescriptors:@[descriptor]]];
		[locationKeysInOrder addObjectsFromArray:[tmpU3 sortedArrayUsingDescriptors:@[descriptor]]];
		[locationKeysInOrder addObjectsFromArray:[tmpBattery sortedArrayUsingDescriptors:@[descriptor]]];
		[locationKeysInOrder addObjectsFromArray:[tmpDrive sortedArrayUsingDescriptors:@[descriptor]]];
		[locationKeysInOrder addObjectsFromArray:[tmpOthers sortedArrayUsingDescriptors:@[descriptor]]];
	}
}

- (float)currentValueForKey:(NSString *)locationKey {
	NSDictionary *tmpDictionary = sensorData[locationKey];
	if (tmpDictionary == nil) return 0;
	
    NSNumber *n = tmpDictionary[GSCurrentValueKey];
    
    if (n != nil) {
        return [n floatValue];
    }
    else {
        return 0;
    }
}

- (void)setCurrentValue:(float)value andUnits:(NSString *)units forLocation:(NSString *)location {
	BOOL needRegen = NO;
	
	// Need to find the right dictionary for this location
    NSDictionary *existingDictionary = sensorData[location];
    NSMutableDictionary *valueDictionary;
    if (existingDictionary != nil) {
        valueDictionary = [existingDictionary mutableCopy];
    }
	
	// If we didn't find it, we need to create a new one and insert it into our collection.
	if (valueDictionary == nil) {
		valueDictionary = [NSMutableDictionary dictionaryWithCapacity:10];
		sensorData[location] = valueDictionary;
		needRegen = YES;
	}
	
	// Set the units
	valueDictionary[GSUnitsKey] = units;
		
	// Set the current value in the sensor data dictionary
	valueDictionary[GSCurrentValueKey] = @(value);
	
	// Set that this sensor is enabled.
	valueDictionary[GSEnable] = @"YES";
	
	// Set the next value in the data set.
	if (valueDictionary[GSDataSetKey] == nil) {
		// we have to create an DataSet for this location.
		DataSet *newSet = [[DataSet alloc] init];
		[newSet resize:(size_t)numSamples];
		[newSet setAllValues:value];
		valueDictionary[GSDataSetKey] = newSet;
	}
	[valueDictionary[GSDataSetKey] setNextValue:value];
	
	// If this location doesn't have a label, generate one.
	if (valueDictionary[GSLabelKey] == nil) {
		if ([location isEqualToString:@"CPU A AD7417 AMB"]) {
			valueDictionary[GSLabelKey] = @"CPU A Ambient";
		}
		else if ([location isEqualToString:@"CPU B AD7417 AMB"]) {
			valueDictionary[GSLabelKey] = @"CPU B Ambient";
		}
		else {
			valueDictionary[GSLabelKey] = location;
		}
	}
				
	
	// Regenerate our location keys if needed
	if (needRegen) [self regenerateLocationKeyOrder];
	
	#ifdef DEBUG
		NSLog(@"Set current value: %f (%@) for location: (%@)", value, units, location);
	#endif
	
	return;
}

- (DataSet *)dataSetForKey:(NSString *)locationKey {
	NSDictionary *tmpDictionary = sensorData[locationKey];
	if (tmpDictionary == nil) return nil;

    return tmpDictionary[GSDataSetKey];
}

- (NSString *)labelForKey:(NSString *)locationKey {
    id label = sensorData[locationKey][GSLabelKey];
    
    if (label == nil) {
        return locationKey;
    }
    else {
        return label;
    }
}

- (void)setDataSize:(int)newNumSamples {
    NSArray *a = [sensorData allKeys];

    for (int i = 0; i < [a count]; i++) {
		[sensorData[a[i]][GSDataSetKey] resize:(size_t)newNumSamples];
    }
    
    numSamples = newNumSamples;
}

- (NSArray<Fan *> *)fanValues {
    if (self.fanCache && ([self.fanCacheCreated timeIntervalSinceNow] > -1)) {
        return self.fanCache;
    }
    
    NSMutableArray *retFans = [NSMutableArray array];
    
    NSDictionary *fansD = [smcSensors fanValues];
    for (NSString *key in [fansD allKeys]) {
        Fan *f = [[Fan alloc] init];
        f.name = key;
        
        id fanD = fansD[key];
        for (NSString *fanDKey in [fanD allKeys]) {
            id fanValue = fanD[fanDKey];
            
            if ([fanValue isKindOfClass:[NSNumber class]]) {
                if ([fanDKey hasSuffix:@"Ac"]) {
                    f.actualSpeed = [fanValue integerValue];
                }
                else if ([fanDKey hasSuffix:@"Tg"]) {
                    f.targetSpeed = [fanValue integerValue];
                }
                else if ([fanDKey hasSuffix:@"Mn"]) {
                    f.minimumSpeed = [fanValue integerValue];
                }
                else if ([fanDKey hasSuffix:@"Mx"]) {
                    f.maximumSpeed = [fanValue integerValue];
                }
            }
        }
        
        [retFans addObject:f];
    }

    self.fanCache = retFans;
    self.fanCacheCreated = [NSDate date];
    
    return retFans;
}

@end

@implementation Fan
@end
