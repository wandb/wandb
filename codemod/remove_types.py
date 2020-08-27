import argparse
import libcst as cst
from libcst import matchers as m, codemod


class RemoveTypesTransformer(codemod.VisitorBasedCodemodCommand):

    DESCRIPTION = "Removes annotations."

    def leave_Param(self, original_node: cst.Param, updated_node: cst.Param):
        return updated_node.with_changes(annotation=None)

    def leave_FunctionDef(self, original_node: cst.FunctionDef,
                          updated_node: cst.FunctionDef):
        return updated_node.with_changes(returns=None)

    def leave_AnnAssign(self, original_node: cst.AnnAssign,
                        updated_node: cst.AnnAssign):
        if updated_node.value is None:
            # Annotate assignments so they can be commented out by a second pass
            return updated_node.with_changes(
                    target=cst.Name("__COMMENT__" + original_node.target.value))
            # return cst.RemoveFromParent()

        return cst.Assign(
            targets=[cst.AssignTarget(target=updated_node.target)],
            value=updated_node.value)
