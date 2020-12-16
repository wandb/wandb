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

/* Modified version from IOPMLibPrivate.c - reduced to the SMC communication part. 
 Derived code follows in the bottom part
 
 */ 

#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#import <Cocoa/Cocoa.h>
#import <IOKit/IOKitLib.h>
#import "SMCInterface.h"

/************ code from IOPMLibPrivate.c starts here: ***************/ 
/* internal defines: */ 
// Todo: verify kSMCKeyNotFound
enum {
    kSMCKeyNotFound = 0x84
};

/* Do not modify - defined by AppleSMC.kext */
enum {
	kSMCSuccess	= 0,
	kSMCError	= 1
};

enum {
	kSMCUserClientOpen  = 0,
	kSMCUserClientClose = 1,
	kSMCHandleYPCEvent  = 2 
};

enum {
    kSMCReadKey         = 5,
	kSMCWriteKey        = 6,
	kSMCGetKeyCount     = 7,
	kSMCGetKeyFromIndex = 8,
	kSMCGetKeyInfo      = 9
};
/* Do not modify - defined by AppleSMC.kext */
typedef struct SMCVersion 
{
    unsigned char    major;
    unsigned char    minor;
    unsigned char    build;
    unsigned char    reserved;
    unsigned short   release;

} SMCVersion;

/* Do not modify - defined by AppleSMC.kext */
typedef struct SMCPLimitData 
{
    uint16_t    version;
    uint16_t    length;
    uint32_t    cpuPLimit;
    uint32_t    gpuPLimit;
    uint32_t    memPLimit;

} SMCPLimitData;

/* Do not modify - defined by AppleSMC.kext */
typedef struct SMCKeyInfoData 
{
    uint32_t            dataSize;
    uint32_t            dataType;
    uint8_t             dataAttributes;

} SMCKeyInfoData;

/* Do not modify - defined by AppleSMC.kext */
typedef struct {
    uint32_t            key;
    SMCVersion          vers;
    SMCPLimitData       pLimitData;
    SMCKeyInfoData      keyInfo;
    uint8_t             result;
    uint8_t             status;
    uint8_t             data8;
    uint32_t            data32;    
    uint8_t             bytes[32];
}  SMCParamStruct;

static IOReturn callSMCFunction(
                                int which, 
                                SMCParamStruct *inputValues, 
                                SMCParamStruct *outputValues) 
{
    IOReturn result = kIOReturnError;
    
    size_t         inStructSize = sizeof(SMCParamStruct);
    size_t         outStructSize = sizeof(SMCParamStruct);
    
    io_connect_t    _SMCConnect = IO_OBJECT_NULL;
    io_service_t    smc = IO_OBJECT_NULL;
    
    smc = IOServiceGetMatchingService(
                                      kIOMasterPortDefault, 
                                      IOServiceMatching("AppleSMC"));
    if (IO_OBJECT_NULL == smc) {
        return kIOReturnNotFound;
    }
    
    result = IOServiceOpen(smc, mach_task_self(), 1, &_SMCConnect);        
    if (result != kIOReturnSuccess || 
        IO_OBJECT_NULL == _SMCConnect) {
        _SMCConnect = IO_OBJECT_NULL;
        goto exit;
    }
    
    result = IOConnectCallMethod(_SMCConnect, kSMCUserClientOpen, 
                                 NULL, 0, NULL, 0, NULL, NULL, NULL, NULL);
    if (result != kIOReturnSuccess) {
        goto exit;
    }
    
    result = IOConnectCallStructMethod(_SMCConnect, which, 
                                       inputValues, inStructSize,
                                       outputValues, &outStructSize);
    
exit:    
    if (IO_OBJECT_NULL != _SMCConnect) {
        IOConnectCallMethod(_SMCConnect, kSMCUserClientClose, 
                            NULL, 0, NULL, 0, NULL, NULL, NULL, NULL);
        IOServiceClose(_SMCConnect);    
    }
    
    return result;
}

/**** Code from IOPMLibPrivate.c stops here. The remainder is implemented by CodeExchange */ 
#pragma mark -
/**** Key types. For more types see <http://www.parhelia.ch/blog/statics/k3_keys.html>  ****/

typedef NS_ENUM(unsigned int, SMCDataType_t) {
    // decoded to NSNumber:
    kSMCDataTypeUInt8 = 'ui8 ',
    kSMCDataTypeUInt16 = 'ui16',
    kSMCDataTypeUInt32 = 'ui32',
    kSMCDataTypeInt8 = 'si8 ',
    kSMCDataTypeInt16 = 'si16',
    kSMCDataTypeFlag = 'flag',
    kSMCDataTypeFPE2  = 'fpe2',
    kSMCDataTypeSP78  = 'sp78',
    kSMCDataTypeFloat  = 'flt ',
    // returned as NSData:
    kSMCDataTypeBuffer = 'ch8*',
    kSMCDataTypeHEX = 'hex_',
    kSMCDataTypeFP88 = 'fp88'
};

@interface SMCCachedKeyInfo : NSObject
@property (nonatomic, assign) FourCharCode type;
@property (nonatomic, assign) uint32_t size;

- (instancetype) init:(SMCKeyInfoData *) info;
@end

@implementation SMCCachedKeyInfo
- (instancetype) init:(SMCKeyInfoData *)keyInfo  {
    if( self = [super init] ) {
        self.size = CFSwapInt32LittleToHost( keyInfo->dataSize );
        self.type = CFSwapInt32LittleToHost( keyInfo->dataType );
    }
    return self;
}
@end

@interface SMCInterface() {
    io_connect_t conn_;
}

@property (readonly) IOReturn openConnection;
@property (strong) NSMutableDictionary *cachedInfos;

- (void) closeConnection;
- (id) uintValueFromSMC:(uint8_t *)data length:(size_t) size ;
- (NSNumber *)floatNumberFromFPE2:(uint8_t *)data length:(size_t) size;
@end


@implementation SMCInterface

- (instancetype) init
{
	self = [super init];
	
	if( self )
	{
        if( [self openConnection] != kIOReturnSuccess ) {
            return nil;
        }
        self.cachedInfos = [NSMutableDictionary dictionary];
	}
	return self;
}

- (void) dealloc
{
	[self closeConnection];
}

- (SMCCachedKeyInfo *) infoForKey:(FourCharCode) key result:(IOReturn *) outResult  {
    NSAssert( sizeof( SMCParamStruct ) == 80, @"Expected SMCParamStruct of size 80" );

    SMCParamStruct  stuffMeIn;
    SMCParamStruct  stuffMeOut;
    IOReturn        ret;
    
    if (key == 0) {
        *outResult = kIOReturnCannotWire;
        return nil;
    }
    
    *outResult = kIOReturnSuccess;
    SMCCachedKeyInfo      *info =  self.cachedInfos[ @(key) ];
    if( info ) { // SMC round trips are expensive. Get rid of some with a cache.
        return info;
    }

    // Determine key's data size
    bzero(&stuffMeIn, sizeof(SMCParamStruct));
    bzero(&stuffMeOut, sizeof(SMCParamStruct));
    
    // UInt32 size =  sizeof(SMCParamStruct);
    stuffMeIn.data8 = kSMCGetKeyInfo;
    stuffMeIn.key = CFSwapInt32HostToLittle( key );
    
    ret = callSMCFunction(kSMCHandleYPCEvent, &stuffMeIn, &stuffMeOut);
   
    if (stuffMeOut.result == kSMCKeyNotFound) {
        *outResult = kIOReturnNotFound;
    } else if (stuffMeOut.result != kSMCSuccess) {
        *outResult = kIOReturnInternalError;
    } else {
        info = [[SMCCachedKeyInfo alloc] init:&stuffMeOut.keyInfo];
        self.cachedInfos[ @(key) ] = info;
    }
    return info;
}


- (id) readValue:(FourCharCode) key error:(NSError **) outError {
    SMCParamStruct  stuffMeIn;
    SMCParamStruct  stuffMeOut;
    IOReturn        ret;
    id              result = nil;
    SMCCachedKeyInfo *keyInfo = nil;
    
    if (key == 0) {
        ret = kIOReturnCannotWire;
        goto exit;
    }
   
    if( outError )
        *outError = nil;
    
    keyInfo = [self infoForKey:key result:&ret];
    if( keyInfo == nil || ret != kIOReturnSuccess ) {
        goto exit;
    }
    
    // Get Key Value
    bzero(&stuffMeIn, sizeof(SMCParamStruct));
    stuffMeIn.data8 = kSMCReadKey;
    stuffMeIn.key = CFSwapInt32HostToLittle( key );
    stuffMeIn.keyInfo.dataSize = CFSwapInt32HostToLittle( keyInfo.size );
    stuffMeIn.keyInfo.dataType = CFSwapInt32HostToLittle( keyInfo.type );
    
    bzero(&stuffMeOut, sizeof(SMCParamStruct));
    ret = callSMCFunction(kSMCHandleYPCEvent, &stuffMeIn, &stuffMeOut);
    if (stuffMeOut.result == kSMCKeyNotFound) {
        ret = kIOReturnNotFound;
        goto exit;
    } else if (stuffMeOut.result != kSMCSuccess) {
        ret = kIOReturnInternalError;
        goto exit;
    }
    
    
    switch( keyInfo.type ) {
        case kSMCDataTypeUInt8:
        case kSMCDataTypeUInt16:
        case kSMCDataTypeUInt32:
            result = [self uintValueFromSMC:stuffMeOut.bytes length:keyInfo.size];
            break;
        case kSMCDataTypeSP78:
			if (stuffMeOut.bytes[0] == 0x84)                                         result = @-124;	// Unstable Temperature
			else if (stuffMeOut.bytes[0] == 0x83)                                    result = @-125;	// Temperature below allowed minimum
			else if (stuffMeOut.bytes[0] == 0x82)                                    result = @-126;	// Sensor failed to initialize
			else if (stuffMeOut.bytes[0] == 0x81)                                    result = @-127;	// Sensor skipped
			else if (stuffMeOut.bytes[0] == 0x80)                                    result = @-128;	// Temperature can't be read
			else if ((stuffMeOut.bytes[0] == 0x7F) && (stuffMeOut.bytes[1] == 0xE7)) result = @127.9f;		// Hot temperature.
			else                                                                     result = [NSNumber numberWithFloat:(((stuffMeOut.bytes[0] * 256 + stuffMeOut.bytes[1]) >> 2)/64.)];
            break;
        case kSMCDataTypeFPE2:
            result = [self floatNumberFromFPE2:stuffMeOut.bytes length:keyInfo.size];
            break;
        case kSMCDataTypeFloat:
            result = [self floatNumberFromFloat:stuffMeOut.bytes length:keyInfo.size];
            break;
        case kSMCDataTypeInt8:
            result = [NSNumber numberWithChar:stuffMeOut.bytes[0]]; 
            break;
        case kSMCDataTypeInt16:
        {
            short value = ((int) stuffMeOut.bytes[0] << 8) + stuffMeOut.bytes[1];
            result = @(value); 
            break;
        }
        case kSMCDataTypeFlag:
            if( keyInfo.size == 1 ) {
                result = [NSNumber numberWithBool:(stuffMeOut.bytes[0] != 0)];
                break;
            }
        default:
            result = [NSData dataWithBytes:stuffMeOut.bytes length:keyInfo.size];
            // result = [self intValueFromSMC:stuffMeOut.bytes length:stuffMeOut.keyInfo.dataSize];
            break;
    }
 exit:
    if( ret && outError ) {
        *outError = [NSError errorWithDomain:NSMachErrorDomain code:ret userInfo:nil];
    }
    return result;
}


- (NSInteger) keyCount
{
    id count = [self readValue:'#KEY' error:nil];
	if ([count isKindOfClass:[NSNumber class]]) {
		return [(NSNumber *)count integerValue];
	}
	else {
		return 0;
	}
}

- (FourCharCode) keyAtIndex:(NSInteger)anIndex {
    SMCParamStruct  stuffMeIn;
    SMCParamStruct  stuffMeOut;
    IOReturn        ret;
        
    // Determine key's data size
    bzero(&stuffMeIn, sizeof(SMCParamStruct));
    bzero(&stuffMeOut, sizeof(SMCParamStruct));
    stuffMeIn.data8 = kSMCGetKeyFromIndex;
    stuffMeIn.data32 = (uint32_t)anIndex;
    
    ret = callSMCFunction(kSMCHandleYPCEvent, &stuffMeIn, &stuffMeOut);
    // keyType = stuffMeOut.keyInfo.dataType;
    return stuffMeOut.key;
}

/* internal functions start here */ 

- (IOReturn) openConnection {
    IOReturn result = kIOReturnError;
    
       io_service_t    smc = IO_OBJECT_NULL;
    
    smc = IOServiceGetMatchingService(
                                      kIOMasterPortDefault, 
                                      IOServiceMatching("AppleSMC"));
    if (IO_OBJECT_NULL == smc) {
        return kIOReturnNotFound;
    }
    
    result = IOServiceOpen(smc, mach_task_self(), 1, &conn_ );        
    if (result != kIOReturnSuccess ) {
        conn_ = IO_OBJECT_NULL;
    } else {
        result = IOConnectCallMethod( conn_, kSMCUserClientOpen, 
                                 NULL, 0, NULL, 0, NULL, NULL, NULL, NULL);
    }
    return result;
}

- (void) closeConnection {
    if (IO_OBJECT_NULL != conn_ ) {
        IOConnectCallMethod(conn_, kSMCUserClientClose, 
                            NULL, 0, NULL, 0, NULL, NULL, NULL, NULL);
        IOServiceClose(conn_);  
        conn_ = IO_OBJECT_NULL;
    }
}



- (id) uintValueFromSMC:(uint8_t *)data length:(size_t) size {
    NSAssert( size > 0, @"SMC data size" );
    uint32_t result = 0L;
    while ( size-- ) {
        result <<= 8;
        result += *data;
        ++data;
    }
    return @(result);
}

- (NSNumber *)floatNumberFromFPE2:(uint8_t *)data length:(size_t) size {
	int exponent = 2; 
    float value = 0;
    int i;
    
    for (i = 0; i < size; i++)
    {
        if (i == (size - 1))
            value += (data[i] & 0xff) >> exponent;
        else
            value += data[i] << (size - 1 - i) * (8 - exponent);
    }
    
    return @(value);
}

- (NSNumber *)floatNumberFromFloat:(uint8_t *)data length:(size_t) size {
    if( size == 4 ) {
        union ConvertFloat {
            float    asFloat;
            UInt32   asInt;
        };
        union ConvertFloat convert;
        
        UInt32 *ip = (UInt32 *)data;
        convert.asInt = CFSwapInt32LittleToHost( *ip );
        return @( convert.asFloat );
    }
    return nil;
}
@end
