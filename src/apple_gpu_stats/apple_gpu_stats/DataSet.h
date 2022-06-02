//
//  DataSet.h
//

#import <Foundation/Foundation.h>

@interface DataSet : NSObject

@property(nonatomic, assign) CGFloat *values;
@property(nonatomic, assign) size_t numValues;
@property(nonatomic, assign) NSInteger currentIndex;

@property(nonatomic, assign) CGFloat min;
@property(nonatomic, assign) CGFloat max;
@property(nonatomic, assign) CGFloat sum;

- (id)initWithContentsOfOtherDataSet:(DataSet *)otherDataSet;

- (CGFloat)average;
- (CGFloat)currentValue;
- (void)valuesInOrder:(CGFloat *)destinationArray;

- (void)reset;
- (void)resize:(size_t)newNumValues;
- (void)setNextValue:(CGFloat)nextVal;
- (void)setAllValues:(CGFloat)value;
- (void)addOtherDataSetValues:(DataSet *)otherDataSet;
- (void)subtractOtherDataSetValues:(DataSet *)otherDataSet;
- (void)divideAllValuesBy:(CGFloat)dividend;

@end