from enum import Enum
from typing import Generic, List, Optional, Type, TypeVar, Union

from messplatz.proto.scpi.types import SCPIEnum, SCPIString, SCPIType

E = TypeVar("E", bound=Enum)


class SCPICommand:
    """
    A SCPI command
    """

    def __init__(self, scope: List["SCPINode"], suffix: str = "", params: List[str] = None,
                 response_type: Optional[Type[SCPIType]] = None):
        self.scope = scope
        self.suffix = suffix
        self.params = params if params is not None else []
        self.response_type = response_type

    def __repr__(self) -> str:
        return f"<SCPICommand: {self.compile()}>"

    def compile(self) -> str:
        """
        Compile the SCPI command
        """
        root = self.scope[0]
        prefix = root.root_prefix if root.parent is None else ""
        base = prefix + ":".join(filter(lambda x: x is not None, [node.scope for node in self.scope]))
        if self.suffix:
            base += f"{self.suffix}"
        if self.params:
            base += " " + ",".join(str(p) for p in self.params)
        return base


class SCPINode:
    """
    A SCPI node
    """

    def __init__(self, scope: str = "", parent: "SCPINode" = None, queryable: bool = False, callable: bool = False, writable: bool = False,
                 response_type: Optional[Type[SCPIType]] = None, root_prefix: str = ""):
        self.scope = scope
        self.response_type = response_type
        self.root_prefix = root_prefix
        self.parent = parent
        self.queryable = queryable
        self.callable = callable
        self.writable = writable

    def query(self, *args, **kwargs) -> SCPICommand:
        """
        Query the SCPI string property
        """

        if not self.queryable:
            raise ValueError(f"SCPI node {self.scope} is not queryable")

        # compute the path to the root node
        path_to_root = []
        current = self
        while current is not None:
            path_to_root.append(current)
            current = current.parent if hasattr(current, "parent") else None

        # create the SCPI command
        path_to_root.reverse()
        return SCPICommand(path_to_root, suffix="?", params=list(args),
                           response_type=self.response_type)

    def __call__(self, *args, **kwargs) -> SCPICommand:
        """
        Call the SCPI string property
        """

        if not self.callable:
            raise ValueError(f"SCPI node {self.scope} is not callable")

        # compute the path to the root node
        path_to_root = []
        current = self
        while current is not None:
            path_to_root.append(current)
            current = current.parent if hasattr(current, "parent") else None

        # create the SCPI command
        path_to_root.reverse()
        return SCPICommand(path_to_root, params=list(args))


class SCPIOnOff(SCPINode):

    """
    A SCPI node for on/off control
    """

    def __init__(self, scope: str = "", parent: "SCPINode" = None):
        super().__init__(scope=scope, parent=parent, queryable=True, callable=True,
                         response_type=SCPIString)

    def on(self) -> SCPICommand:
        return self.__call__("ON")

    def off(self) -> SCPICommand:
        return self.__call__("OFF")

    def __call__(self, value: Union[str, int, bool]) -> SCPICommand:

        if isinstance(value, str):
            value = value.upper()

        if value in {"ON", "OFF", 0, 1, True, False}:
            
            if not isinstance(value, str):
                value = "ON" if value else "OFF"
            
            return super().__call__(value)

        return super().__call__(value)

    def query(self) -> SCPICommand:
        return super().query()


class SCPIEnumNode(SCPINode, Generic[E]):

    """
    A SCPI node whose value is one option of the given enum type,
    e.g. SCPIEnumNode(WaveformMode, scope="MODE", parent=self)
    """

    def __init__(self, enum_type: Type[E], scope: str = "", parent: "SCPINode" = None):
        response_type = type(f"{enum_type.__name__}Type", (SCPIEnum,), {"enum": enum_type})
        super().__init__(scope=scope, parent=parent, queryable=True, callable=True,
                         response_type=response_type)
        self.enum_type = enum_type

    def __call__(self, value: E) -> SCPICommand:

        if not isinstance(value, self.enum_type):
            raise TypeError(f"SCPI node {self.scope} expects a {self.enum_type.__name__}, got {value!r}")

        return super().__call__(self.response_type.format(value))

    def query(self) -> SCPICommand:
        return super().query()


class SCPISourceNode(SCPINode):

    """
    A SCPI node selecting a source, either an analog channel or a math channel,
    e.g. source(channel=1) -> CHAN1, source(math=2) -> MATH2
    """

    def __init__(self, scope: str = "", parent: "SCPINode" = None):
        super().__init__(scope=scope, parent=parent, queryable=True, callable=True,
                         response_type=SCPIString)

    def __call__(self, channel: Optional[int] = None, math: Optional[int] = None) -> SCPICommand:

        if (channel is None) == (math is None):
            raise ValueError(f"SCPI node {self.scope} expects exactly one of channel or math")

        if channel is not None:
            return super().__call__(f"CHAN{int(channel)}")

        return super().__call__(f"MATH{int(math)}")

    def query(self) -> SCPICommand:
        return super().query()


class SCPICoreSpec(SCPINode):
    """
    The SCPI core specification
    """

    def __init__(self):
        self.scope = None
        self.parent = None
        self.queryable = False
        self.callable = False
        self.writable = False
        self.root_prefix = "*"

        self.identification : SCPINode = SCPINode("IDN", self, queryable=True, response_type=SCPIString)
        self.reset : SCPINode = SCPINode("RST", self, callable=True)
        self.clear : SCPINode = SCPINode("CLS", self, callable=True)
        self.operation_complete : SCPINode = SCPINode("OPC", self, queryable=True)
        self.wait : SCPINode = SCPINode("WAI", self, callable=True)
        self.self_test : SCPINode = SCPINode("TST", self, callable=True)

