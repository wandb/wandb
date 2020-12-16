/*
 *  Interface to read SMC based sensor data in a convenient Cocoa-ish way
 *  (C) CodeExchange 2012, licensed under the APSL
 */

/*
 * Copyright (c) 2004 Apple Computer, Inc. All rights reserved.
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

#import <Cocoa/Cocoa.h>

@class SMCInterface;

@interface SMCSensors : NSObject

@property(strong) NSDictionary *descriptionsForSMCKeys;

@property(nonatomic, readonly, strong) NSSet<NSString *> *unknownTemperatureKeys; // property descs for temp properties with description
@property(nonatomic, readonly, strong) NSSet<NSString *> *knownTemperatureKeys;   // property descs for temp properties with description

/// returns an plain dict of values with their 4cc IDs.
/// contains only values where a known conversion from the SMC data type to NSNumber / NDSData is implemented in SMCInterface
@property(readonly, copy) NSDictionary *allValues;

/// as far as their meaning is known (==guessable), the values have human readable keys
/// Fan values - returns an NSDictionary of NSDictionaries
@property(readonly, copy) NSDictionary *fanValues;

/// Temperature senor values
/// withUnknownSensors: include sensors where humanReadableNameForKey will fail
/// return an NSDictionary with key: SMCSensorName, value: NSNumber with temperature in Celsius
- (NSDictionary *)temperatureValuesExtended:(BOOL)withUnknownSensors;
- (NSDictionary *)powerValuesExtended:(BOOL)withUnknownSensors;

/// additional sensors (motion etc.).
@property(readonly, copy) NSDictionary *sensorValues;

/// lookup a human readbale description of the 4 character string key.
/// will return key, if no description can be found
- (NSString *)humanReadableNameForKey:(NSString *)key;

@end
