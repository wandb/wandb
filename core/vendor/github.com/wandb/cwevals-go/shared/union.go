// File generated from our OpenAPI spec by Stainless.

package shared

type UnionString string

func (UnionString) ImplementsCaseFieldValueUnionParam()                                      {}
func (UnionString) ImplementsCaseValueUnionParam()                                           {}
func (UnionString) ImplementsEvaluationQueryResultListResponseRowsGroupUnion()               {}
func (UnionString) ImplementsEvaluationQueryResultListResponseRowsMetricsValueUnion()        {}
func (UnionString) ImplementsEvaluationVersionQueryResultListResponseRowsGroupUnion()        {}
func (UnionString) ImplementsEvaluationVersionQueryResultListResponseRowsMetricsValueUnion() {}

type UnionBool bool

func (UnionBool) ImplementsCaseFieldValueUnionParam()                                      {}
func (UnionBool) ImplementsCaseValueUnionParam()                                           {}
func (UnionBool) ImplementsEvaluationQueryResultListResponseRowsGroupUnion()               {}
func (UnionBool) ImplementsEvaluationQueryResultListResponseRowsMetricsValueUnion()        {}
func (UnionBool) ImplementsEvaluationVersionQueryResultListResponseRowsGroupUnion()        {}
func (UnionBool) ImplementsEvaluationVersionQueryResultListResponseRowsMetricsValueUnion() {}

type UnionInt int64

func (UnionInt) ImplementsEvaluationQueryResultListResponseRowsGroupUnion()               {}
func (UnionInt) ImplementsEvaluationQueryResultListResponseRowsMetricsValueUnion()        {}
func (UnionInt) ImplementsEvaluationVersionQueryResultListResponseRowsGroupUnion()        {}
func (UnionInt) ImplementsEvaluationVersionQueryResultListResponseRowsMetricsValueUnion() {}

type UnionFloat float64

func (UnionFloat) ImplementsCaseFieldValueUnionParam()                                      {}
func (UnionFloat) ImplementsCaseValueUnionParam()                                           {}
func (UnionFloat) ImplementsEvaluationQueryResultListResponseRowsGroupUnion()               {}
func (UnionFloat) ImplementsEvaluationQueryResultListResponseRowsMetricsValueUnion()        {}
func (UnionFloat) ImplementsEvaluationVersionQueryResultListResponseRowsGroupUnion()        {}
func (UnionFloat) ImplementsEvaluationVersionQueryResultListResponseRowsMetricsValueUnion() {}
