import enum

from messplatz.proto.scpi.core import SCPINode, SCPIOnOff, SCPIEnumNode, SCPISourceNode
from messplatz.proto.scpi.types import SCPIBlock, SCPIFloat


class _Unit1000HD_TouchSpec(SCPINode):

    def __init__(self, scope: str = "TOUCH", parent: SCPINode = None):
        super().__init__(scope=scope, parent=parent)

        self.lock = SCPIOnOff(scope="LOCK", parent=self)


class _Unit1000HD_SystemSpec(SCPINode):

    def __init__(self, scope: str = "SYST", parent: SCPINode = None):
        super().__init__(scope=scope, parent=parent)

        self.lock = SCPIOnOff(scope="LOCK", parent=self)
        self.touch = _Unit1000HD_TouchSpec(parent=self)


class _Unit1000HD_ChannelSpec(SCPINode):

    def __init__(self, channel_number: int, scope: str = "CHAN", parent: SCPINode = None):
        super().__init__(scope=f"{scope}{channel_number}", parent=parent)

        self.__channel_number = channel_number

        self.display = SCPIOnOff(scope="DISP", parent=self)

    @property
    def channel_number(self) -> int:
        return self.__channel_number


class _Unit1000HD_WaveformSpec(SCPINode):

    class Formats(enum.Enum):
        WORD = "WORD"
        DWORD = "DWORD"
        ASCII = "ASCII"

    class Modes(enum.Enum):
        NORMAL = "NORMAL"
        RAW = "RAW"

    def __init__(self, scope: str = "WAV", parent: SCPINode = None):
        super().__init__(scope=scope, parent=parent)

        self.source = SCPISourceNode(scope="SOUR", parent=self)
        self.mode = SCPIEnumNode(self.Modes, scope="MODE", parent=self)
        self.format = SCPIEnumNode(self.Formats, scope="FORMAT", parent=self)
        self.data = SCPINode(scope="DATA", parent=self, queryable=True, response_type=SCPIBlock)

        # scaling parameters, see :WAVeform:XINCrement? ... :WAVeform:YREFerence?
        self.x_increment = SCPINode(scope="XINC", parent=self, queryable=True, response_type=SCPIFloat)
        self.x_origin = SCPINode(scope="XOR", parent=self, queryable=True, response_type=SCPIFloat)
        self.x_reference = SCPINode(scope="XREF", parent=self, queryable=True, response_type=SCPIFloat)
        self.y_increment = SCPINode(scope="YINC", parent=self, queryable=True, response_type=SCPIFloat)
        self.y_origin = SCPINode(scope="YOR", parent=self, queryable=True, response_type=SCPIFloat)
        self.y_reference = SCPINode(scope="YREF", parent=self, queryable=True, response_type=SCPIFloat)


class Unit1000HDSCPISpec(SCPINode):

    def __init__(self):

        self.root_prefix = ":"
        self.parent = None
        self.scope = None

        self.run = SCPINode(scope="RUN", parent=self, callable=True)
        self.stop = SCPINode(scope="STOP", parent=self, callable=True)
        self.autoset = SCPINode(scope="AUTO", parent=self, callable=True)

        self.system = _Unit1000HD_SystemSpec(scope="SYST", parent=self)
        self.waveform = _Unit1000HD_WaveformSpec(scope="WAV", parent=self)


    def channel(self, channel_number: int) -> _Unit1000HD_ChannelSpec:
        return _Unit1000HD_ChannelSpec(channel_number=channel_number, parent=self)