/*
 * Copyright (c) 2012 CodeExchange All rights reserved.
 *
 * @APPLE_LICENSE_HEADER_START@
 * 
 * This file contains Original Code and/or Modifications of Original Code
 * as defined in and that are subject to the Apple Public Source License
 * Version 2.0 (the 'License'). You may not use this file except in
 * compliance with the License. Please obtain a copy of the License at
 * http://www.opensource.apple.com/apsl/ and read it before using this
 * file.
 * 
 * The Original Code and all software distributed under the License are
 * distributed on an 'AS IS' basis, WITHOUT WARRANTY OF ANY KIND, EITHER
 * EXPRESS OR IMPLIED, AND APPLE HEREBY DISCLAIMS ALL SUCH WARRANTIES,
 * INCLUDING WITHOUT LIMITATION, ANY WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE, QUIET ENJOYMENT OR NON-INFRINGEMENT.
 * Please see the License for the specific language governing rights and
 * limitations under the License.
 * 
 * @APPLE_LICENSE_HEADER_END@
 */


#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#import <Cocoa/Cocoa.h>
#import "SMCSensors.h"
#import "SMCInterface.h"

@interface SMCSensors()
@property (nonatomic, strong)  SMCInterface *smc;
@property (nonatomic, strong)  NSDictionary<NSString *, NSString *> *keyDescriptions; // string <-> string for names
@property (nonatomic, strong)  NSDictionary<NSString *, NSMutableSet *> *fanDescriptions; // Fan name <=> NSSet with associated keys
@property (nonatomic, strong)  NSSet<NSString *> *unknownTemperatureKeys; // property descs for temp properties with description
@property (nonatomic, strong)  NSSet<NSString *> *knownTemperatureKeys; // property descs for temp properties with description
@property (nonatomic, strong)  NSSet<NSString *> *unknownPowerKeys; // property descs for temp properties with description
@property (nonatomic, strong)  NSSet<NSString *> *knownPowerKeys; // property descs for temp properties with description

- (int) c4String:(char *)string matchesPattern:(const char *)pattern;
- (void) buildKeyCache;
- (BOOL) readSMCValues:(NSSet *) smcKeys toDictionary:(NSMutableDictionary *) destDict;
- (NSString *) dictKeyFromInt:(uint32_t) key;
- (uint32_t) keyFromString:(NSString *) key;
@end

typedef NS_ENUM(int, DescriptionMatch_t) {
    kNoMatch = -1,
    kDirectMatch = 0x100
}; 

@implementation SMCSensors

- (instancetype) init
{
	self = [super init];
	
	if( self )
	{
		self.smc = [[SMCInterface alloc] init];
		
        [self setupDescriptions];
		
		[self buildKeyCache];
	}
	return self;
}

- (void) setupDescriptions {
    // see <http://www.parhelia.ch/blog/statics/k3_keys.html>
    self.descriptionsForSMCKeys = @{
                        @"TA?P": @"Ambient",
                        @"TA?V": @"Ambient",
                        @"Ta?P": @"Ambient",
                        @"TB?T": @"Bottom Sensor",
                        @"TC?C": @"CPU Core",
                        @"TCMz": @"M1 GPU",
                        @"TMVR": @"Neural Engine",
                        @"TC?D": @"CPU Die",
                        @"TC?H": @"CPU Heatsink",
                        @"TC?P": @"CPU Proximity",
                        @"TCGC": @"iGPU",
                        @"TG?D": @"GPU Die",
                        @"TG?H": @"GPU Heatsink",
                        @"TG?P": @"GPU Proximity",
                        @"TH?F": @"SSD",
                        @"TH?P": @"HD Proximity",
                        @"Th?H": @"Heatsink",
                        @"TI?P": @"Thunderbolt",
                        @"TL?P": @"LCD Proximity",
                        @"TM?P": @"Memory Proximity",
                        @"TM?S": @"Memory",
                        @"Tm?P": @"Misc. local",
                        @"TMA?": @"DIMM A",
                        @"TMB?": @"DIMM B",
                        @"TN?D": @"Northbridge Die",
                        @"TN?H": @"Northbridge Heatsink",
                        @"TN?P": @"Northbridge Proximity",
                        @"TO?P": @"Optical Drive",
                        @"TL?P": @"LCD",
                        @"Tp?C": @"Power Supply",
                        @"Tp?P": @"Power Supply",
                        @"Ts?P": @"Palm Rest",
                        @"TS?C": @"Expansion Slot",
                        @"TTTD": @"T2 Die",
                        @"TW?P": @"Airport",
                        // sensors:
                        @"ALV0": @"Ambient Light Left",
                        @"ALV1": @"Ambient Light Right",
                        @"MSLD": @"Clamshell",
                        @"MO_X": @"Motion-X",
                        @"MO_Y": @"Motion-Y",
                        @"MO_Z": @"Motion-Z",
                        @"MOCN": @"Motion",
                        // Noise: (sourced from http://www.assembla.com/spaces/fakesmc/wiki/Known_SMC_Keys/history )
                        @"dBA?": @"Noise near Fan",
                        @"dBAH": @"Noise near HD",
                        @"dBAT": @"Total Noise",
                        // Watts:
                        @"PCOC": @"CPU Package Total",
                        @"PMVR": @"GPU / Neural Engine Total",
                        @"PC0R": @"CPU Rail Power",
                        @"PG0R": @"GPU Rail Power",
                        @"PM0R": @"Memory Rail",
                        @"PSTR": @"System Total Power",
                        // Fans:
                        @"F?Ac": @"Fan Speed",
                        @"F?Mn": @"Fan Minimum Speed",
                        @"F?Mx": @"Fan Maximum Speed",
                        @"F?Sf": @"Fan Safe Speed",
                        @"F?Mt": @"Fan Maximum Target",
                        @"F?Tg": @"Fan Target Speed",
                        @"FS! ": @"Fan Forced Speed",
        };
}

- (NSString *) humanReadableNameForKey:(NSString *)key {
    NSString *result = self.keyDescriptions[key];
    return result ? result : key;
}

- (NSDictionary *) temperatureValuesExtended:(BOOL) includeUnknownSensors
{
	NSMutableDictionary *resultDict = [NSMutableDictionary dictionary];
    [self readSMCValues:self.knownTemperatureKeys toDictionary:resultDict];
    if( includeUnknownSensors ) {
        [self readSMCValues:self.unknownTemperatureKeys toDictionary:resultDict];
    }
    return resultDict;
}

- (NSDictionary *) powerValuesExtended:(BOOL) includeUnknownSensors
{
    NSMutableDictionary *resultDict = [NSMutableDictionary dictionary];
    [self readSMCValues:self.knownPowerKeys toDictionary:resultDict];
    if( includeUnknownSensors ) {
        [self readSMCValues:self.unknownPowerKeys toDictionary:resultDict];
    }
    return resultDict;
}

- (NSDictionary *) fanValues
{
    uint32_t      forcedBits;
    NSError *error = nil;
    
	NSMutableDictionary *resultDict = [NSMutableDictionary dictionary];
	// totalFans = [[smc_ readValue:'FNum' error:&error] intValue];
    
    forcedBits = [[self.smc readValue:'FS! ' error:&error] intValue]; // Value is base 16!?!
    
    for( NSString *fanIndexString in [self.fanDescriptions allKeys] ) {
        int fanIndex = [fanIndexString intValue];
        NSMutableDictionary *fanDict = [NSMutableDictionary dictionary];
        [resultDict setValue:fanDict forKey:[NSString stringWithFormat:@"Fan #%d", fanIndex]];
        
        NSSet *smcKeys = self.fanDescriptions[fanIndexString];
        [self readSMCValues:smcKeys toDictionary:fanDict];
        fanDict[@"Forced"] = [NSNumber numberWithBool:(forcedBits & (1 << fanIndex))];
    }
    return resultDict;
}

- (NSDictionary *)allValues
{
    NSInteger     totalKeys, i;
    uint32_t      key;
  
	NSMutableDictionary *dict = [NSMutableDictionary dictionary];
    totalKeys = [self.smc keyCount];
    for (i = 0; i < totalKeys; i++)
    {
        key = [self.smc keyAtIndex:i];
        id value = [self.smc readValue:key error:nil];
        if( value )
            [dict setValue:value forKey:[self dictKeyFromInt:key]]; 
    }    
    return dict;
}


- (NSDictionary *) sensorValues
{ // try to gather the motion sensor values:

	NSMutableDictionary *values = [NSMutableDictionary dictionary];
    NSError *error;
    
    values[@"ALV0"] = [self.smc readValue:'ALV0' error:&error];
    values[@"ALV1"] = [self.smc readValue:'ALV1' error:&error];
    values[@"MSLD"] = [self.smc readValue:'MSLD' error:&error];
    values[@"MO_X"] = [self.smc readValue:'MO_X' error:&error];
    values[@"MO_Y"] = [self.smc readValue:'MO_Y' error:&error];
    values[@"MO_Z"] = [self.smc readValue:'MO_Z' error:&error];
    values[@"MOCN"] = [self.smc readValue:'MOCN' error:&error];
	return values;
}

#pragma mark -
#pragma mark internal

- (NSSet<NSString *> *) readSMCKeys {
    NSInteger smcKeyCount = [self.smc keyCount];
    NSMutableSet *smcKeys = [NSMutableSet setWithCapacity:smcKeyCount];

    // traverse the available keys, prepare them for sorting
    for( NSInteger i = 0; i < smcKeyCount; i++) {
        uint32_t key = [self.smc keyAtIndex:i];
            
        NSString *smcKeyString = [self dictKeyFromInt:key];
        [smcKeys addObject:smcKeyString];
    }
    return smcKeys;
}

- (void) buildKeyCache {
    NSMutableDictionary<NSString *, NSString *> *descriptions = [NSMutableDictionary dictionary];
    NSMutableDictionary<NSString *, NSMutableSet *> *fanDescriptions = [NSMutableDictionary dictionary];
    
    NSMutableSet *unknownTempKeys = [NSMutableSet set];
    NSMutableSet *knownTempKeys = [NSMutableSet set];
    NSMutableSet *unknownOtherKeys = [NSMutableSet set];
    NSMutableSet *knownPowerKeys = [NSMutableSet set];
    NSMutableSet *unknownPowerKeys = [NSMutableSet set];
    
    NSSet<NSString *> *smcKeys = [self readSMCKeys];
    
    NSArray<NSString *> *keyDescriptionsWithWildcard = [self.descriptionsForSMCKeys.allKeys filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^( NSString *s, id dontCare ){ return [s containsString:@"?"]; }]];
    
    // now set up description lookup:
    for( NSString *currentKey in smcKeys ) {
		char keyChar[5] = "";
        NSString *smcKeyDescription = nil;
		int indexInKey = 0;
        BOOL isFanKey, isTemperatureKey, isPowerKey;
        
		[currentKey getCString:keyChar maxLength:5 encoding:NSASCIIStringEncoding];
        
        isFanKey = keyChar[0] == 'F' && isdigit( keyChar[1] );
        isTemperatureKey = keyChar[0] == 'T';
        isPowerKey = keyChar[0] == 'P';
		
        // Direct match?
        smcKeyDescription = self.descriptionsForSMCKeys[currentKey];
        if( smcKeyDescription == nil ) {
            // No direct match, find a wildcard match
            for (NSString *key in keyDescriptionsWithWildcard) {
                indexInKey = [self c4String:keyChar matchesPattern:[key UTF8String]];
                if (indexInKey != kNoMatch) {
                    smcKeyDescription = self.descriptionsForSMCKeys[key];
                    break;
                }
            }
            
            if (smcKeyDescription) {
                // Filter out non-consecutive sensors:
                if (indexInKey > 1) {
                    NSString *prevKey = [currentKey stringByReplacingOccurrencesOfString:[NSString stringWithFormat:@"%X", indexInKey] withString:[NSString stringWithFormat:@"%X", indexInKey-1]];
                    if (![smcKeys containsObject:prevKey]) {
                        smcKeyDescription = nil;
                    }
                }
                
                // Figure out if we should add a digit (only if there are more than one with this name).
                BOOL appendIndexToDescription = NO;
                if ( !isFanKey ) {
                    if (indexInKey == 0  )	{
                        // if the key is of form XXX0, see if there is also XXX1
                        NSString *sensorAtIndexOneKey = [currentKey stringByReplacingOccurrencesOfString:@"0" withString:@"1"];
                        appendIndexToDescription = [smcKeys containsObject:sensorAtIndexOneKey];
                        
                    } else {
                        appendIndexToDescription = YES;
                    }
                }
                if (appendIndexToDescription) {
                    smcKeyDescription = [smcKeyDescription stringByAppendingFormat:@" #%d", indexInKey];
                }
            }
        }
        
        descriptions[currentKey] = smcKeyDescription;
        
        if( isTemperatureKey ) {
            if( smcKeyDescription ) {
                [knownTempKeys addObject:currentKey];
            } else {
                [unknownTempKeys addObject:currentKey];
            }
        } else if ( isFanKey ) {
            NSString *fanKey = [NSString stringWithFormat:@"%c", keyChar[1]];
            NSMutableSet *fanValues = fanDescriptions[fanKey];
            if( !fanValues ) {
                fanValues = [NSMutableSet setWithCapacity:5];
                fanDescriptions[fanKey] = fanValues;
            }
            [fanValues addObject:currentKey];
        } else if (isPowerKey) {
            if( smcKeyDescription) {
                [knownPowerKeys addObject:currentKey];
            } else {
                [unknownPowerKeys addObject:currentKey];
            }
        } else {
            [unknownOtherKeys addObject:currentKey];
        }
	}	
    
    self.keyDescriptions = descriptions;
    self.unknownTemperatureKeys = unknownTempKeys;
    self.knownTemperatureKeys = knownTempKeys;
    self.knownPowerKeys = knownPowerKeys;
    self.unknownPowerKeys = unknownPowerKeys;

    self.fanDescriptions = fanDescriptions;
}

- (NSString *) dictKeyFromInt:(uint32_t) key {
    return [NSString stringWithFormat:@"%c%c%c%c", 
            ((key >> 24) & 0xff), 
            ((key >> 16) & 0xff), 
            ((key >> 8) & 0xff),  
            (key & 0xff)];
}

- (uint32_t) keyFromString:(NSString *) key {
    uint32_t result = 0L;
    for( int i = 0; i < 4; ++i ) {
        result <<= 8;
        result += [key characterAtIndex:i];
    }
    return result;
}

// Returns 
// - kNoMatch if no match, 
// - kDirectMatch if match, 
// - 0-15 if a pattern digit is matched.  Input strings better be 4 characters long!

- (int) c4String:(char *)string matchesPattern:(const char *)pattern {
	DescriptionMatch_t retVal = kNoMatch;
	int length = 4;
	if (strlen(string) != length || strlen(pattern) != length) 
        return kNoMatch;

	retVal = kDirectMatch;
	int i;
	for (i = 0; i < length; i++) {
		if (pattern[i] == '?') {
			// Found a wildard, set the ret val and go on to the next index.
			if (string[i] >= '0' && string[i] <= '9') 
                retVal = string[i] - '0';
			else if (string[i] >= 'a' && string[i] <= 'f') 
                retVal = string[i] - 'a' + 10;
			else if (string[i] >= 'A' && string[i] <= 'F') 
                retVal = string[i] - 'A' + 10;
			else 
                return kNoMatch;
			continue;
		}
		else if (pattern[i] == string[i]) {
			// Character matched, go on to the next index.
			continue;
		}
		else {
			// This character didn't match.
			return kNoMatch;
		}
	}
	return retVal;
}

- (BOOL) readSMCValues:(NSSet *) smcKeys toDictionary:(NSMutableDictionary *) destDict
{
    NSError *error = nil; 
    BOOL success = YES;
    
    for( NSString *aKey in smcKeys  ) {
        id value = [self.smc readValue:[self keyFromString:aKey] error:&error];
        if( !error ) {
            destDict[aKey] = value;
        } else {
            success = NO;
        }
    }
    return success;
}

@end
