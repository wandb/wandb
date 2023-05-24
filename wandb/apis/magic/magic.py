import libcst as cst
import libcst.matchers as m
from typing import Union


class FrameworkFinder(cst.CSTVisitor):
    def __init__(self):
        self.using_keras = False
        self.using_lightning = False

    def _check_imported_name(self, name):
        if name in {"keras", "pytorch_lightning"}:
            self.using_keras = name == "keras"
            self.using_lightning = name == "pytorch_lightning"

    def visit_Import(self, node: cst.Import) -> None:
        for imported_name in node.names:
            if m.matches(imported_name.name, m.Name()):
                self._check_imported_name(imported_name.name.value)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.module and self._get_module_str(node.module).startswith(
            "tensorflow.keras"
        ):
            self.using_keras = True

    def _get_module_str(self, module: cst.BaseExpression) -> str:
        if m.matches(module, m.Name()):
            return module.value
        elif m.matches(module, m.Attribute()):
            return f"{self._get_module_str(module.value)}.{module.attr.value}"
        return ""


class WandbImportAdder(cst.CSTTransformer):
    def __init__(self):
        self.has_wandb_import = False

    def visit_Import(self, node: cst.Import) -> None:
        if any(m.matches(name.name, m.Name("wandb")) for name in node.names):
            self.has_wandb_import = True

    def leave_Module(
        self, original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        if self.has_wandb_import:
            return updated_node

        wandb_import = cst.Import(names=[cst.ImportAlias(name=cst.Name("wandb"))])
        wandb_init = cst.Expr(
            value=cst.Call(func=cst.Attribute(cst.Name("wandb"), cst.Name("init")))
        )
        return updated_node.with_changes(
            body=[
                cst.SimpleStatementLine(body=[wandb_import]),
                cst.EmptyLine(),
                cst.SimpleStatementLine(body=[wandb_init]),
                cst.EmptyLine(),
            ]
            + original_node.body
        )


class KerasCallbacksVarFinder(cst.CSTVisitor):
    def __init__(self):
        self.callback_var_name = None
        self.model_fit_call = None

    def visit_Call(self, node: cst.Call) -> None:
        if self._is_model_fit_call(node):
            # Save the model.fit call for later
            self.model_fit_call = node
            # Iterate over the existing arguments
            for arg in node.args:
                # If we find the callbacks keyword argument, save the variable name for later
                if (
                    arg.keyword is not None
                    and arg.keyword.value == "callbacks"
                    and isinstance(arg.value, cst.Name)
                ):
                    self.callback_var_name = arg.value.value

    def _is_model_fit_call(self, node: cst.Call) -> bool:
        return isinstance(node.func, cst.Attribute) and node.func.attr.value == "fit"


class KerasWandbCallbackAdder(cst.CSTTransformer):
    def __init__(self, callback_var_name, model_fit_call):
        super().__init__()
        self.callback_var_name = callback_var_name
        self.model_fit_call = model_fit_call

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        if self.callback_var_name or not self._is_model_fit_call(original_node):  # noop
            return updated_node

        # Check if the callbacks argument already exists
        for i, arg in enumerate(updated_node.args):
            if (
                arg.keyword is not None
                and arg.keyword.value == "callbacks"
                and isinstance(arg.value, cst.List)
            ):
                # If the callbacks argument exists and it's a list, add to it
                new_args = list(updated_node.args)
                new_args[i] = cst.Arg(
                    keyword=cst.Name("callbacks"),
                    value=cst.List(
                        elements=list(arg.value.elements)
                        + [self._wandb_callback_arg()],
                    ),
                )
                return updated_node.with_changes(args=tuple(new_args))
        # If the callbacks argument doesn't exist, add it as the last kwarg
        new_args = list(updated_node.args)
        new_args.append(
            cst.Arg(
                keyword=cst.Name("callbacks"),
                value=cst.List(
                    elements=[self._wandb_callback_arg()],
                ),
            )
        )
        return updated_node.with_changes(args=tuple(new_args))

    def leave_Assign(
        self, original_node: cst.Assign, updated_node: cst.Assign
    ) -> Union[cst.Assign, cst.RemoveFromParent]:
        if not (
            isinstance(original_node.targets[0].target, cst.Name)
            and original_node.targets[0].target.value == self.callback_var_name
        ):  # noop
            return updated_node

        if isinstance(original_node.value, cst.List):
            # Add the wandb callback to the existing list
            return updated_node.with_changes(
                value=cst.List(
                    elements=list(original_node.value.elements)
                    + [self._wandb_callback_arg()]
                )
            )

    def _wandb_callback_arg(self):
        return cst.Element(
            value=cst.Call(
                func=cst.Attribute(
                    cst.Attribute(cst.Name("wandb"), cst.Name("keras")),
                    cst.Name("WandbCallback"),
                )
            )
        )

    def _is_model_fit_call(self, node: cst.Call) -> bool:
        return isinstance(node.func, cst.Attribute) and node.func.attr.value == "fit"


class TrainerLoggerVarFinder(cst.CSTVisitor):
    def __init__(self):
        self.logger_var_name = None
        self.trainer_init_call = None

    def visit_Call(self, node: cst.Call) -> None:
        if self._is_trainer_init_call(node):
            # Save the Trainer initialization call for later
            self.trainer_init_call = node
            # Iterate over the existing arguments
            for arg in node.args:
                # If we find the logger keyword argument, save the variable name for later
                if (
                    arg.keyword is not None
                    and arg.keyword.value == "logger"
                    and isinstance(arg.value, cst.Name)
                ):
                    self.logger_var_name = arg.value.value

    def _is_trainer_init_call(self, node: cst.Call) -> bool:
        return (
            isinstance(node.func, cst.Attribute) and node.func.attr.value == "Trainer"
        )


class TrainerWandbLoggerAdder(cst.CSTTransformer):
    def __init__(self):
        self.logger_var_name = None

    def _is_trainer_init_call(self, node):
        return m.matches(node, m.Call(func=m.Attribute(attr=m.Name("Trainer"))))

    def _wandb_logger_arg(self):
        return cst.Call(
            func=cst.Attribute(
                value=cst.Attribute(
                    value=cst.Name("pl"),
                    attr=cst.Name("loggers"),
                ),
                attr=cst.Name("WandbLogger"),
            ),
            args=[],
        )

    def visit_Assign(self, node):
        if m.matches(node, m.Assign(targets=[m.Name()])):
            self.logger_var_name = node.targets[0].target.value
        return node

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        if self._is_trainer_init_call(original_node):
            new_args = list(updated_node.args)
            for i, arg in enumerate(new_args):
                if arg.keyword is not None and arg.keyword.value == "logger":
                    if isinstance(arg.value, cst.List):
                        # If it's a list, add to it
                        new_args[i] = cst.Arg(
                            keyword=cst.Name("logger"),
                            value=cst.List(
                                elements=list(arg.value.elements)
                                + [cst.Element(value=self._wandb_logger_arg())],
                            ),
                        )
                    else:
                        # If it's a single logger or a call, make it a list
                        new_args[i] = cst.Arg(
                            keyword=cst.Name("logger"),
                            value=cst.List(
                                elements=[
                                    cst.Element(value=arg.value),
                                    cst.Element(value=self._wandb_logger_arg()),
                                ],
                            ),
                        )
                    return updated_node.with_changes(args=tuple(new_args))
            # If the logger argument doesn't exist, add it as the last kwarg
            new_args.append(
                cst.Arg(
                    keyword=cst.Name("logger"),
                    value=cst.List(
                        elements=[cst.Element(value=self._wandb_logger_arg())],
                    ),
                )
            )
            return updated_node.with_changes(args=tuple(new_args))
        return updated_node


def auto_wandb(fname):
    with open(fname) as f:
        module = cst.parse_module(f.read())

    # Determine the framework being used
    finder = FrameworkFinder()
    module.visit(finder)

    # 1. Import wandb; wandb.init()
    import_adder = WandbImportAdder()
    module = module.visit(import_adder)

    # 2. Add relevant callbacks and loggers
    if finder.using_keras:
        # Find the callbacks variable and model.fit call
        keras_finder = KerasCallbacksVarFinder()
        module.visit(keras_finder)

        # Add the callback
        adder = KerasWandbCallbackAdder(
            keras_finder.callback_var_name, keras_finder.model_fit_call
        )
        module = module.visit(adder)

    if finder.using_lightning:
        lightning_finder = TrainerLoggerVarFinder()
        module.visit(lightning_finder)

        adder = TrainerWandbLoggerAdder()
        module = module.visit(adder)

    # Return the modified code
    with open(fname.replace(".py", "_wandb_logging.py"), "w") as f:
        f.write(module.code)

    return module.code
