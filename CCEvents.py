from typing import Any, Union
import CCUtils

# a class composed of event types in CrossCode.

class Event_Step:
    def __init__(self, type: str) -> None:
        self._type = type

    @property
    def type(self): return self._type

    def asDict(self) -> dict:
        return {"type": self.type}

class _ChangeVar(Event_Step):
    def __init__(self, type: str, varName: str, value: Any, changeType: str) -> None:
        super().__init__(type),
        self.varName = varName
        self.value = value
        self.changeType = changeType
    

    @property
    def changeType(self):
        return self._changeType

    @changeType.setter
    def changeType(self, value):
        if value not in ["set", "add"]:
            raise Exception(f"Invalid changeType '{value}'")
        self._changeType = value

    def asDict(self) -> dict:
        return super().asDict() | {
            "varName": self.varName,
            "value": self.value,
            "changeType": self.changeType
        }

class _Message(Event_Step):
    def __init__(self, type: str, character: CCUtils.Character, message: str) -> None:
        super().__init__(type)
        self.character = character
        self.message = message
    
    def asDict(self) -> dict:
        return super().asDict() | {
            "message": {
                "en_US": self.message
            },
            "person": {
                "person": self.character.internalName,
                "expression": self.character.expression
            }
        }

class CHANGE_VAR_BOOL(_ChangeVar):
    def __init__(self, varName: str, value: bool) -> None:
        super().__init__("CHANGE_VAR_BOOL", varName, value, "set")
    
    def asDict(self) -> dict:
        return super().asDict()

class CHANGE_VAR_NUMBER(_ChangeVar):
    def __init__(self, varName: str, value: int, changeType: str) -> None:
        super().__init__("CHANGE_VAR_NUMBER", varName, value, changeType)

class SHOW_SIDE_MSG(_Message):
    def __init__(self, character: CCUtils.Character, message: str) -> None:
        super().__init__("SHOW_SIDE_MSG", character, message)

class SHOW_MSG(_Message):
    def __init__(self, character: CCUtils.Character, message: str, autoContinue: bool = False) -> None:
        super().__init__("SHOW_MSG", character, message)
        self.autoContinue = autoContinue
    
    def asDict(self) -> dict:
        return super().asDict() | {"autoContinue": self.autoContinue}

class IF(Event_Step):
    def __init__(self, condition: str, *, thenEvent: list[Event_Step] = [], elseEvent: list[Event_Step] = []) -> None:
        super().__init__(type = "IF")
        self.condition: str = condition
        self.thenStep: list[Event_Step] = thenEvent
        self.elseStep: list[Event_Step] = elseEvent
    
    @property
    def withElse(self) -> bool: return len(self.elseStep) > 0

    def asDict(self) -> dict:        
        if self.withElse:
            return super().asDict() | {
                "withElse": self.withElse,
                "condition": self.condition,
                "thenStep": [event.asDict() for event in self.thenStep],
                "elseStep": [event.asDict() for event in self.elseStep]
            }
        else:
            return super().asDict() | {
                "withElse": self.withElse,
                "condition": self.condition,
                "thenStep": [event.asDict() for event in self.thenStep],
            }

class WAIT(Event_Step):
    def __init__(self, time: float, ignoreSlowdown: bool = False) -> None:
        super().__init__("WAIT")
        self.time = float(time)
        self.ignoreSlowdown = ignoreSlowdown

    def asDict(self) -> dict:
        return super().asDict() | {
            "time": self.time,
            "ignoreSlowDown": self.ignoreSlowdown
        }



class CommonEvent:
    def __init__(self, *, type: dict, loopCount: int, frequency: str = "REGULAR", repeat: str = "ONCE", condition: str = "true",  
            eventType: str = "PARALLEL", overrideSideMessage: bool = False, events: Union[dict[int, Event_Step], list[Event_Step]] = {}) -> None:
        self.frequency: str = frequency
        self.repeat: str = repeat
        self.condition: str = condition
        self.eventType: str = eventType
        self.type: dict = type
        self.loopCount: int = loopCount
        self.overrideSideMessage: bool = overrideSideMessage
        self.event: dict[int, Event_Step] = {}
        if events:
            if isinstance(events, list):
                if not all(isinstance(value, Event_Step) for value in events):
                    raise Exception
                for i in range(len(events)):
                    self.event[i+1] = events[i]
            elif isinstance(events, dict):
                if not (all(isinstance(key, int) for key in events.keys()) or \
                all(isinstance(value, Event_Step) for value in events.values())):
                    raise Exception
                else:
                    self.event = events

    @property
    def runOnTrigger(self) -> list[int]:
        return list(self.event.keys())

    def asDict(self):
        return {
            "frequency": self.frequency,
            "repeat": self.repeat,
            "condition": self.condition,
            "eventType": self.eventType,
            "runOnTrigger": self.runOnTrigger,
            "event": [event.asDict() for event in self.event.values()],
            "overrideSideMessage": self.overrideSideMessage,
            "loopCount": self.loopCount,
            "type": self.type
        }