import argparse
import libcst as cst
from libcst import matchers as m, codemod


class RemoveTypesTransformer(codemod.VisitorBasedCodemodCommand):

    DESCRIPTION = "Removes annotations."

    def leave_Param(self, original_node: cst.Param, updated_node: cst.Param):
        return updated_node.with_changes(annotation=None)

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ):
        return updated_node.with_changes(returns=None)

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ):
        if updated_node.value is None:
            if isinstance(original_node.target.value, cst.Name):
                # TODO: (cvp) this works for `self._func: SomeType` annotations, may not be robust...
                updated_name = original_node.target.value.value + "_" + original_node.target.attr.value
            else:
                updated_name = original_node.target.value
            # Annotate assignments so they can be commented out by a second pass
            return updated_node.with_changes(
                target=cst.Name("__COMMENT__" + updated_name)
            )
            # return cst.RemoveFromParent()

        return cst.Assign(
            targets=[cst.AssignTarget(target=updated_node.target)],
            value=updated_node.value,
        )
