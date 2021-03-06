import json
import os, re, sys, argparse
import CCEvents as Events
import CCUtils
from CCEvents import ChangeVarType
from enum import Enum

# ~ crosscode eventscript v1.5.0 parser, by EL ~
# to run:
#   python cc-eventscript-parser.py <input text file>
# REQUIRES PYTHON 3.10 OR ABOVE!
# to make a text file:
#   see readme

verbose = False

class CCES_Exception(Exception): pass

class CCEventRegex:
    # matches lines that start with "#" or "//"
    comment = re.compile(r"(?<!\\)(?:#|\/\/).*")
    # matches strings of the form "import (fileName)"
    importFile = re.compile(r"^import\s+(?:(?:\.\/)?patches\/)?(?P<directory>(?:[.\w]+[\\\/])*)(?P<filename>[\w+-]+){1}?(?:\.json)?$", flags=re.I)
    includeFile = re.compile(r"^include\s+(?:(?:\.\/)?patches\/)?(?P<directory>(?:[.\w]+[\\\/])*)(?P<filename>[\w+-]+){1}?(?:\.json)?$", flags=re.I)
    
    filepath = re.compile(r"^(?P<directory>(?:[.\w]+[\\\/])*)(?P<filename>\S+)$")
    # matches strings of the form "(character) > (expression): (message)" or "(character) > (expression) (message)"
    dialogue = re.compile(r"^(?P<character>.+)\s*>\s*(?P<expression>[A-Z\d_]+)[\s:](?P<dialogue>.+)$")
    # matches strings of the form "message (number)", insensitive search
    eventHeader = re.compile(r"^(?:message|event) (?P<eventNum>\d+):?$", flags=re.I)
    # matches strings of the form "== title =="
    title = re.compile(r"^== *(?P<ignore>!)?(?P<eventTitle>\S+) *==$")
    # matches strings of the form "(key): (value)"
    property = re.compile(r"^(?P<property>\w+)\s*:\s*(?P<value>.+)$")
    # matches "set (varname) (true/false)"
    setVarBool = re.compile(r"^set\s+(?P<varName>\S+)\s*(?P<sign>[= |^])\s*(?P<value>true|false)$", flags=re.I)
    # matches "set (varname) (+/-/=) (number)"
    setVarNum = re.compile(r"^set\s+(?P<varName>\S+)\s*(?P<operation>[=+\-*/%|^])\s*(?P<value>\d+)$", flags=re.I)

    label = re.compile(r"label +(?P<name>\S+)", flags=re.I)
    gotoLabel = re.compile(r"goto +(?P<name>\S+)(?: +if +(?P<condition>.+))?", flags=re.I)

    propertyType = re.compile(r"^type(?:\.(?P<property>\S+))?\s*:\s*(?P<value>.+)", flags = re.I)
    listOfNumbers = re.compile(r"^(?:\d+,\s*)+")
    listOfStrings = re.compile(r"^(?:\S+,\s*)+")

    # matches "if (condition)", "else", and  "endif" respectively
    ifStatement = re.compile(r"^if (?P<condition>.+)", flags=re.I)
    elseStatement = re.compile(r"^else$", flags=re.I)
    endifStatement = re.compile(r"^endif$", flags=re.I)

class EventItemType(Enum):
    STANDARD_EVENT = 1
    IMPORT = 2
    INCLUDE = 3

class EventItem:
    def __init__(self, eventType, filePath: str, event: Events.CommonEvent | None = None) -> None:
        self.eventType = eventType
        if not CCEventRegex.filepath.match(filePath): raise CCES_Exception(f"Error: Invalid file path {filePath}!")
        self.filepath = filePath
        self.event = event

    def genPatchStep(self) -> dict:
        fixedFilename = re.sub(r"^(\.\/)","mod:", self.filepath)
        match self.eventType:
            case EventItemType.IMPORT | EventItemType.STANDARD_EVENT:
                return {
                    "type": "IMPORT",
                    "src": fixedFilename
                }
            case EventItemType.INCLUDE:
                return {
                    "type": "INCLUDE",
                    "src": fixedFilename
                }
            case _:
                raise CCES_Exception("Unknown patch type!")


def processDialogue(inputString: str) -> Events.SHOW_SIDE_MSG:
    messageMatch = CCEventRegex.dialogue.match(inputString)
    character = CCUtils.Character(*messageMatch.group("character", "expression"))
    message = messageMatch.group("dialogue").replace("\\n","\n")

    messageEvent = Events.SHOW_SIDE_MSG(character, message)
    return messageEvent


def processEvents(eventStrs: list[str]) -> list[Events.Event_Step]:
    workingEvent: list[Events.Event_Step] = []
    ifCount: int = 0
    inIf: bool = False
    hasElse: bool = False
    buffer: list[str] = []

    for line in eventStrs:
        line = line.strip()
        
        # if (condition)
        if match := CCEventRegex.ifStatement.match(line):
            if not inIf:
                ifEvent = Events.IF(match.group("condition"))
                inIf = True
            else:
                buffer.append(line)
            ifCount += 1

        # endif
        elif CCEventRegex.endifStatement.match(line):
            # only count the last "endif" of a block
            if ifCount > 1:
                buffer.append(line)
                ifCount -= 1
            # make sure that there is no excess endifs
            elif ifCount < 1:
                raise CCES_Exception("Error: 'endif' found outside of if block")
            # process if statement for the corresponding if
            else:
                if hasElse: ifEvent.elseStep = processEvents(buffer)
                else: ifEvent.thenStep = processEvents(buffer)
                ifCount = 0
                workingEvent.append(ifEvent)
                inIf = False
                hasElse = False
                buffer = []

        # else
        elif CCEventRegex.elseStatement.match(line):
            if (not inIf):
                raise CCES_Exception("'else' statement found outside of if block")
            elif ifCount > 1:
                buffer.append(line)
            elif hasElse:
                raise CCES_Exception("multiple 'else' statements found inside of if block")
            else:
                hasElse = True
                ifEvent.thenStep = processEvents(buffer)
                buffer = []

        # adds to string buffer for later processing
        elif inIf:
            buffer.append(line)

        # dialogue
        elif match := CCEventRegex.dialogue.match(line):
            workingEvent.append(processDialogue(line))

        # set var = bool
        elif match := CCEventRegex.setVarBool.match(line):
            varName, sign, originalValue = match.group("varName", "sign", "value")
            value = (originalValue.lower() == "true")
            operation: ChangeVarType
            match sign:
                case "=" | " ":
                    operation = ChangeVarType.SET
                case "|":
                    operation = ChangeVarType.OR
                case "^":
                    operation = Events.ChangeVarType.XOR 

            workingEvent.append(Events.CHANGE_VAR_BOOL(varName, value, operation))

        # set var +|-|= num
        elif match := CCEventRegex.setVarNum.match(line):
            varName, sign, number = match.group("varName", "operation", "value")
            value = int(number)
            operation: ChangeVarType
            match sign:
                case "=":
                    operation = ChangeVarType.SET
                case "+":
                    operation = ChangeVarType.ADD
                case "-":
                    operation = ChangeVarType.SUB
                case "*":
                    operation = ChangeVarType.MUL
                case "/":
                    operation = ChangeVarType.DIV
                case "%":
                    operation = ChangeVarType.MOD
                case "|":
                    operation = ChangeVarType.OR
                case "^":
                    operation = Events.ChangeVarType.XOR 
            workingEvent.append(Events.CHANGE_VAR_NUMBER(varName, value, operation))

        elif match := CCEventRegex.label.match(line):
            workingEvent.append(Events.LABEL(match.group("name")))

        elif match := CCEventRegex.gotoLabel.match(line):
            if match.group("condition"): # if a condition exists, it will do GOTO_LABEL_WHILE instead.
                workingEvent.append(Events.GOTO_LABEL_WHILE(*match.group("name", "condition")))
            else:
                workingEvent.append(Events.GOTO_LABEL(match.group("name")))

    #ensure that ifs are properly terminated
    if inIf:
        raise CCES_Exception("'if' found without corresponding 'endif'")

    return workingEvent


def handleEvent(eventStrs: list[str]) -> Events.CommonEvent:
    event = Events.CommonEvent(type={}, loopCount = 3)

    eventNumber: int = 0
    buffer: list[str] = []
    trackMessages: bool = False
    workingEvent = {}

    for line in eventStrs:
        if match := CCEventRegex.eventHeader.match(line):
            if trackMessages:
                try:
                    workingEvent.thenStep = processEvents(buffer)
                except CCES_Exception as e:
                    raise CCES_Exception(f"error in event {eventNumber}") from e
                event.event[eventNumber] = workingEvent
                buffer = []

            eventNumber += 1
            workingEvent = Events.IF(f"call.runCount == {eventNumber}")
            trackMessages = True

        elif trackMessages:
            buffer.append(line) 

        elif match := CCEventRegex.propertyType.match(line):
            propertyName, propertyValue = match.group("property", "value")
            propertyValue = propertyValue.strip()
            if propertyName is not None:
                
                if CCEventRegex.listOfNumbers.match(propertyValue):
                    typeValueList = propertyValue.split(",")
                    event.type[propertyName] = [int(value) for value in typeValueList]

                elif CCEventRegex.listOfStrings.match(propertyValue):
                    typeValueList = propertyValue.split(",")
                    event.type[propertyName] = [value.strip() for value in typeValueList]

                elif re.match(r"^\d+$", propertyValue):
                    event.type[propertyName] = int(propertyValue)
                else:
                    event.type[propertyName] = propertyValue
                    
            else:
                event.type["type"] = propertyValue

        elif match := CCEventRegex.property.match(line):
            propertyName, propertyValue = match.group("property", "value")
            propertyName = propertyName.lower()
            
            match propertyName:
                case "frequency": event.frequency = propertyValue
                case "repeat": event.repeat = propertyValue
                case "condition": event.condition = propertyValue
                case "eventtype": event.eventType = propertyValue
                case "loopcount": event.loopCount = int(propertyValue)
                case _: print(f"Unrecognized property \"{propertyName}\", skipping...", file = sys.stderr)

        else:
            print(f"Unrecognized line \"{line}\", ignoring...", file = sys.stderr)
    if buffer:
        try:
            workingEvent.thenStep = processEvents(buffer)
        except CCES_Exception as e:
            raise CCES_Exception(f"error in message {eventNumber}") from e
        event.event[eventNumber] = workingEvent
    if event.type == {}:
        event.type = {"killCount": 0, "type": "BATTLE_OVER"}
    return event


def parseFiles(inputFilenames: list[str], runRecursively: bool = False) -> dict[str, EventItem]:
    eventDict: dict[str, EventItem] = {}
    filelist: list[str] = []
    def readFile(filename):
        nonlocal eventDict
        eventTitle: str = ""
        buffer: list[str] = []
        ignoreEvent: bool = False
        with open(filename, "r", encoding='utf8') as inputFile:
            for line in inputFile:
                # remove comments and strip excess whitespace
                line = re.sub(CCEventRegex.comment, "", line).strip()

                # skip blank lines
                if (not line): continue
                
                # handle file imports
                if match := CCEventRegex.importFile.match(line):
                    filename = f"./patches/{match.group('directory')}{match.group('filename')}.json"
                    eventTitle = match.group("filename")
                    if eventTitle in eventDict: raise KeyError(f"Duplicate event name '{eventTitle}' found in input file.")
                    eventDict[eventTitle] = EventItem(EventItemType.IMPORT, filename)
                    eventTitle = ""

                if match := CCEventRegex.includeFile.match(line):
                    filename = f"./patches/{match.group('directory')}{match.group('filename')}.json"
                    eventTitle = match.group("filename")
                    if eventTitle in eventDict: raise KeyError(f"Duplicate event name '{eventTitle}' found in input file.")
                    eventDict[eventTitle] = EventItem(EventItemType.INCLUDE, filename)
                    eventTitle = ""

                elif match := CCEventRegex.title.match(line):
                    # check that the event isn't empty so it only runs if there's actually something there
                    if buffer: 
                        eventDict[eventTitle].event = handleEvent(buffer)
                        eventTitle = ""

                    # set the current event and clear the buffer
                    eventTitle = match.group("eventTitle").replace("/",".")
                    filename = f"./patches/{eventTitle}.json"
                    buffer = []
                    
                    if match.group("ignore"):
                        ignoreEvent = True
                        continue
                    ignoreEvent = False
                    if eventTitle in eventDict: raise KeyError("Duplicate event name found in input file.")
                    eventDict[eventTitle] = EventItem(EventItemType.STANDARD_EVENT, filename, None)

                # add anything missing to buffer
                else:
                    if not ignoreEvent: buffer.append(line)

            # process any final events if one is present
            if buffer: eventDict[eventTitle].event = handleEvent(buffer)
    
    
    if runRecursively:
        for item in os.listdir(inputFilenames[0]):
            if (not item.startswith("!")) and re.match(r".*\.cces", item):
                filelist.append(f"{inputFilenames[0]}/{item}")
    else:
        filelist = inputFilenames
    for filename in filelist:
        try: 
            readFile(filename)
        except CCES_Exception as e:
            raise Exception(f"Error in {filename}: ") from e
    return eventDict

def generatePatchFile(events: dict[str, EventItem]) -> list[dict]:
    patchDict: list[dict] = []
    patchDict.append({"type": "ENTER", "index": "commonEvents"})
    for event in events.values():
        patchDict.append(event.genPatchStep())
    patchDict.append({"type": "EXIT"})
    return patchDict

def writeEventFiles(events: dict[str, EventItem], indentation = None) -> None:
    os.makedirs("./patches/", exist_ok = True)
    for eventName, eventInfo in events.items():
        filename = eventInfo.filepath
        directoryMatch = CCEventRegex.filepath.match(filename)
        if directoryMatch and directoryMatch.group("directory"): os.makedirs(directoryMatch.group("directory"), exist_ok= True)
        if eventInfo.eventType == EventItemType.STANDARD_EVENT:
            if eventInfo.event is None: continue
            if verbose: print(f"Writing file '{filename}'.")
            with open(filename, "w+") as jsonFile:
                json.dump({eventName: eventInfo.event.asDict()}, jsonFile, indent = indentation)

def writeDatabasePatchfile(patchDict: dict, filename: str, indentation = None) -> None:
    filename = filename.strip()
    fileMatch = CCEventRegex.filepath.match(filename)
    os.makedirs(fileMatch.group("directory"), exist_ok = True)
    if verbose:
        print("Writing patch file at ./assets/data/database.json.patch")
    with open(filename, "w+") as patchFile:
        json.dump(patchDict, patchFile, indent = indentation)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description= "Process a cc-eventscript file and produce the relevant .json and patch files.")
    parser.add_argument("file", help="The eventscript file(s) to be processed. A file path if -r is enabled.", nargs = "+")
    parser.add_argument("-i", "--indent", type = int, default = None, dest = "indentation", metavar = "NUM", nargs = "?", const = 4, help = "the indentation outputted files should use, if any. if supplied without a number, will default to 4 spaces")
    parser.add_argument("-v", "--verbose", action="store_true", help = "increases verbosity of output")
    parser.add_argument("-r", action = "store_true", dest = "recursive", help = "will parse all files in a single directory ending in '.cces', rather than a single file. ")
    
    databaseGroup = parser.add_mutually_exclusive_group()
    databaseGroup.add_argument("--no-patch-file", action = "store_false", dest = "genPatch", help = "do not generate a 'database.json.patch' file")
    databaseGroup.add_argument("-p", "--patch-file", default = "./assets/data/database.json.patch", dest = "databaseFile", metavar = "DATABASE", help = "the location of the database patch file")



    args = parser.parse_args()
    inputFiles = args.file
    verbose = args.verbose

    allEvents = parseFiles(inputFiles, args.recursive)
    writeEventFiles(allEvents, args.indentation)
    if args.genPatch: writeDatabasePatchfile(generatePatchFile(allEvents), args.databaseFile, args.indentation)
