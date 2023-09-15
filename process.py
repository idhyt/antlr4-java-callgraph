"""
    基于 ANTLR(https://github.com/antlr/antlr4.git) 的 Java 语法解析器, 用于解析 Java 语法树并生成callgraph
    运行时依赖: antlr4-python3-runtime
"""
import argparse
from typing import List, Optional, Dict
import asyncio
from pathlib import Path
import logging
from antlr4 import FileStream, CommonTokenStream, ParseTreeWalker

from parser.JavaLexer import JavaLexer
from parser.JavaParser import JavaParser
from parser.JavaParserListener import JavaParserListener

logging.basicConfig(
    format='%(asctime)s %(name)s | %(levelname)s | %(message)s',
    datefmt='%Y-%M-%d %H:%M:%S',
    level=logging.INFO)
logger = logging.getLogger(__name__)


class ParmType:
    name: str = ''
    type: str = ''

    def __init__(self, *, name: str, type_: str) -> None:
        self.name = name
        self.type = type_

    @property
    def json(self) -> dict:
        return vars(self)


class FieldType:
    type: str = ''
    define: str = ''

    def __init__(self, *, type_: str, define_: str) -> None:
        self.type = type_
        self.define = define_

    @property
    def json(self) -> dict:
        return vars(self)


class Statement:
    value: str = ''
    line: int = 0
    column: int = 0

    def __init__(self, *, value: str, line: int, column: int) -> None:
        self.value = value
        self.line = line
        self.column = column

    @property
    def json(self) -> dict:
        return vars(self)


class JavaMethod:
    name: str = ''
    start: int = 0
    stop: int = 0
    depth: int = 0
    parameters: List[ParmType] = []
    return_type: str = ''
    statements: List[Statement] = []

    def __init__(self, **kwargs) -> None:
        self.parameters = []
        self.statements = []
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    @property
    def json(self) -> dict:
        return {
            'name': self.name,
            'start': self.start,
            'stop': self.stop,
            'depth': self.depth,
            'parameters': [parm.json for parm in self.parameters],
            'return_type': self.return_type,
            'statements': [call.json for call in self.statements]
        }


class JavaClass:
    name: str = ''
    extends: str = ''
    implements: List[str] = []
    fields: List[FieldType] = []
    methods: Dict[str, JavaMethod] = {}
    statements: List[Statement] = []

    def __init__(self, **kwargs) -> None:
        self.implements = []
        self.fields = []
        self.methods = {}
        self.statements = []

        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    @property
    def json(self) -> dict:
        return {
            'name':
            self.name,
            'extends':
            self.extends,
            'implements':
            self.implements,
            'fields': [field.json for field in self.fields],
            'methods':
            dict((key, value.json) for key, value in self.methods.items()),
            'statements': [call.json for call in self.statements]
        }


class JavaFileAst:
    package_name: str = ''
    imports: List[str] = []
    classes: Dict[str, JavaClass] = {}

    def __init__(self) -> None:
        self.imports = []
        self.classes = {}

    @property
    def json(self) -> dict:
        return {
            'package_name':
            self.package_name,
            'imports':
            self.imports,
            'classes':
            dict((key, value.json) for key, value in self.classes.items())
        }

    @property
    def dot(self) -> str:
        digraph = ['digraph "callGraph" {']
        for name, class_ in self.classes.items():
            digraph.append(f'"{name}"')
            for stmt in class_.statements:
                digraph.append(f'"{name}" -> "{stmt.value}";')
            for method_name, method in class_.methods.items():
                digraph.append(f'"{method_name}"')
                digraph.append(f'"{name}" -> "{method_name}";')
                for stmt in method.statements:
                    digraph.append(f'"{method_name}" -> "{stmt.value}";')
        digraph.append('}')
        return '\n'.join(digraph)


class CollectListener(JavaParserListener):

    def __init__(self):
        self._ast: JavaFileAst = JavaFileAst()
        self._deep_class: Dict[int, JavaClass] = {}
        self._deep: int = 0
        self._current_method: Optional[JavaMethod] = None

    def print_stage(self, stage: str):
        logger.debug(f'deep={self._deep} - {stage}')

    def parse_implements_block(self, ctx):
        self.print_stage(f'parse_implements_block: {ctx.getText()}')
        implements_child_count = int(ctx.getChildCount())
        result = []
        if implements_child_count == 1:
            impl_class = ctx.getChild(0).getText()
            result.append(impl_class)
        elif implements_child_count > 1:
            for i in range(implements_child_count):
                if i % 2 == 0:
                    impl_class = ctx.getChild(i).getText()
                    result.append(impl_class)
        return result

    def parse_class_block(self, ctx):
        self.print_stage(f'parse_class_block: {ctx.getChild(1).getText()}')
        child_count = int(ctx.getChildCount())
        class_name, extends, implements = '', '', ''
        if child_count == 7:
            class_name = ctx.getChild(1).getText()
            extends = ctx.getChild(3).getChild(0).getText()
            implements = self.parse_implements_block(ctx.getChild(5))
        elif child_count == 5:
            class_name = ctx.getChild(1).getText()
            c3 = ctx.getChild(2).getText()
            if c3 == 'implements':
                implements = self.parse_implements_block(ctx.getChild(3))
            elif c3 == 'extends':
                extends = ctx.getChild(3).getChild(0).getText()
        elif child_count == 3:
            class_name = ctx.getChild(1).getText()
        elif child_count == 2:
            class_name = self._deep_class[self._deep].name

        if not class_name:
            raise Exception('Class name is not found')
        return class_name, extends, implements

    def parse_method_params_block(self, ctx):
        self.print_stage(f'parse_method_params_block: {ctx.getText()}')
        params_exist_check = int(ctx.getChildCount())
        result = []

        if params_exist_check == 3:
            params_child_count = int(ctx.getChild(1).getChildCount())
            if params_child_count == 1:
                param_type = ctx.getChild(1).getChild(0).getChild(0).getText()
                param_name = ctx.getChild(1).getChild(0).getChild(1).getText()
                result.append(ParmType(type_=param_type, name=param_name))

            elif params_child_count > 1:
                for i in range(params_child_count):
                    if i % 2 == 0:
                        param_type = ctx.getChild(1).getChild(i).getChild(
                            0).getText()
                        param_name = ctx.getChild(1).getChild(i).getChild(
                            1).getText()
                        result.append(
                            ParmType(type_=param_type, name=param_name))

        return result

    # Enter a parse tree produced by JavaParser#packageDeclaration.
    def enterPackageDeclaration(self,
                                ctx: JavaParser.PackageDeclarationContext):
        self.print_stage(
            f'enterPackageDeclaration: {ctx.start.line} {ctx.getText()}')
        self._ast.package_name = ctx.qualifiedName().getText()

    # Exit a parse tree produced by JavaParser#packageDeclaration.
    def exitPackageDeclaration(self,
                               ctx: JavaParser.PackageDeclarationContext):
        self.print_stage(
            f'exitPackageDeclaration: {ctx.start.line} {ctx.getText()}')

    # Enter a parse tree produced by JavaParser#importDeclaration.
    def enterImportDeclaration(self, ctx: JavaParser.ImportDeclarationContext):
        self.print_stage(
            f'enterImportDeclaration: {ctx.start.line} {ctx.getText()}')
        self._ast.imports.append(ctx.qualifiedName().getText())

    # Enter a parse tree produced by JavaParser#classDeclaration.
    def enterClassDeclaration(self, ctx: JavaParser.ClassDeclarationContext):
        self.print_stage(
            f'enterClassDeclaration: {ctx.start.line} {ctx.getChild(1).getText()}'
        )
        name, extends, implements = self.parse_class_block(ctx)
        self._deep += 1
        self._ast.classes[name] = JavaClass(name=name,
                                            extends=extends,
                                            implements=implements)
        self._deep_class[self._deep] = self._ast.classes[name]

    # Exit a parse tree produced by JavaParser#classDeclaration.
    def exitClassDeclaration(self, ctx: JavaParser.ClassDeclarationContext):
        self.print_stage(
            f'exitClassDeclaration: {ctx.start.line} {ctx.getChild(1).getText()}'
        )
        self._deep_class.pop(self._deep)
        self._deep -= 1

    # Enter a parse tree produced by JavaParser#fieldDeclaration.
    def enterFieldDeclaration(self, ctx: JavaParser.FieldDeclarationContext):
        self.print_stage(
            f'enterFieldDeclaration: {ctx.start.line} {ctx.getText()}')
        class_name, _, _ = self.parse_class_block(
            ctx.parentCtx.parentCtx.parentCtx.parentCtx)

        current_class = self._deep_class[self._deep]
        if class_name != current_class.name:
            raise Exception(
                f'Class name is {class_name} is not equal {current_class.name}'
            )
        self._ast.classes[current_class.name].fields.append(
            FieldType(type_=ctx.getChild(0).getText(),
                      define_=ctx.getChild(1).getText()))

    # Enter a parse tree produced by JavaParser#methodDeclaration.
    def enterMethodDeclaration(self, ctx: JavaParser.MethodDeclarationContext):
        method_name = ctx.getChild(1).getText()
        self.print_stage(
            f'enterMethodDeclaration: {ctx.start.line} {method_name}')
        current_class = self._deep_class[self._deep]

        if method_name not in current_class.methods:
            self._ast.classes[
                current_class.name].methods[method_name] = JavaMethod(
                    name=method_name,
                    return_type=ctx.getChild(0).getText(),
                    start=ctx.start.line,
                    stop=ctx.stop.line,
                    depth=ctx.depth(),
                    parameters=self.parse_method_params_block(ctx.getChild(2)))
            # set current method
            self._current_method = self._ast.classes[
                current_class.name].methods[method_name]
        else:
            # TODO bugfix, function overloading in java
            # raise Exception(
            #     f'Method name {method_name} is duplicated in {current_class.name}'
            # )
            logger.warning(
                f'{method_name} is a overloading, ignore it in this version.')

    # Exit a parse tree produced by JavaParser#methodDeclaration.
    def exitMethodDeclaration(self, ctx: JavaParser.MethodDeclarationContext):
        self.print_stage(
            f'exitMethodDeclaration: {ctx.start.line} {ctx.getChild(1).getText()}'
        )
        # reset current method
        self._current_method = None

    # Enter a parse tree produced by JavaParser#methodCall.
    def enterMethodCall(self, ctx: JavaParser.MethodCallContext):
        self.print_stage(f'enterMethodCall: {ctx.start.line} {ctx.getText()}')
        statement = Statement(value=ctx.getChild(0).getText(),
                              line=ctx.start.line,
                              column=ctx.start.column)
        # maybe is anonymous function in class like class { { var a = 1; ...} }
        if self._current_method is None:
            current_class = self._deep_class[self._deep]
            self._ast.classes[current_class.name].statements.append(statement)
        else:
            self._current_method.statements.append(statement)

    # Enter a parse tree produced by JavaParser#enumDeclaration.
    def enterEnumDeclaration(self, ctx: JavaParser.EnumDeclarationContext):
        self.print_stage('enterEnumDeclaration as enterClassDeclaration')
        self.enterClassDeclaration(ctx)

    # Exit a parse tree produced by JavaParser#enumDeclaration.
    def exitEnumDeclaration(self, ctx: JavaParser.EnumDeclarationContext):
        self.print_stage('exitEnumDeclaration as exitClassDeclaration')
        self.exitClassDeclaration(ctx)

    def get_ast(self):
        return self._ast


class JavaCallGraph:
    name = 'java'

    @classmethod
    def process(cls,
                input_path: str,
                output_path: Optional[str] = None) -> None:
        listener = CollectListener()
        parser = JavaParser(
            CommonTokenStream(
                JavaLexer(FileStream(input_path, encoding='utf-8'))))
        walker = ParseTreeWalker()
        walker.walk(listener, parser.compilationUnit())
        if output_path:
            with open(output_path, encoding='utf-8', mode='w') as f:
                f.write(listener.get_ast().dot)

    @classmethod
    async def create(cls, *, input_path: Path, output_path: Path,
                     percent: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, cls.process,
                                   str(input_path.absolute()),
                                   str(output_path.absolute()))

        if not output_path.is_file():
            logger.error(
                f'[{percent}] create {cls.name} callgraph failed for {input_path}'
            )
            return

        logger.info(
            f'[{percent}] create {cls.name} callgraph success for {input_path}'
        )


async def main(input: str) -> None:
    input_path = Path(input)
    files = []
    if input_path.is_file():
        files.append(input_path)
    else:
        files = list(input_path.glob('**/*.java'))

    tasks = [
        JavaCallGraph.create(input_path=src,
                             output_path=src.with_suffix('.dot'),
                             percent=f'{index+1}/{len(files)}')
        for index, src in enumerate(files)
    ]

    await asyncio.gather(*tasks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Demo of argparse')
    parser.add_argument('-i',
                        '--input',
                        dest='input',
                        required=True,
                        help='input file or directory')
    parser.add_argument('-v',
                        '--verbose',
                        dest='verbose',
                        action='store_true',
                        default=False,
                        help='verbose mode')
    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    asyncio.run(main(args.input))