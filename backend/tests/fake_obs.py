"""A stand-in for OBS + obs-websocket, so OBS tests never need a real OBS."""

import base64
from pathlib import Path
from types import SimpleNamespace

PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"

GAME_WINDOW = "FortuneOx:UnityWndClass:FortuneOx.exe"
NOTES_WINDOW = "notes.txt - Notepad:Notepad:Notepad.exe"
MINIMISED_WINDOW = "Minimised:SomeClass:min.exe"


def scene_item(
    name: str = "Window Capture", *, enabled: bool = True, item_id: int = 1, **transform
) -> dict:
    """A plain, untouched window capture as OBS reports it in GetSceneItemList."""
    return {
        "sceneItemId": item_id,
        "sourceName": name,
        "sourceType": "OBS_SOURCE_TYPE_INPUT",
        "inputKind": "window_capture",
        "isGroup": None,
        "sceneItemEnabled": enabled,
        "sceneItemTransform": {
            "sourceWidth": 766.0,
            "sourceHeight": 1101.0,
            "scaleX": 1.0,
            "scaleY": 1.0,
            "rotation": 0.0,
            "cropLeft": 0,
            "cropRight": 0,
            "cropTop": 0,
            "cropBottom": 0,
            **transform,
        },
    }


class FakeObs:
    """Shared OBS state; one FakeClient per websocket connection."""

    def __init__(self, accepting: bool = True) -> None:
        self.accepting = accepting
        self.recording = False
        self.requests: list[tuple[str, dict | None]] = []
        self.rejected: dict[str, str] = {}
        self.reject_codes: dict[str, int] = {}
        self.scene_items: list[dict] = [scene_item()]
        # Window capture: which windows exist (value -> size; 0x0 = cannot be captured),
        # the one currently captured, and how long OBS keeps reporting the previous size.
        self.windows: dict[str, tuple[int, int]] = {
            GAME_WINDOW: (766, 1101),
            NOTES_WINDOW: (500, 400),
            MINIMISED_WINDOW: (0, 0),
        }
        self.window: str | None = GAME_WINDOW
        self.reported_size: tuple[int, int] = (766, 1101)
        self.stale_polls = 0
        self.input_names: set[str] = {"Window Capture"}
        self.video = {
            "baseWidth": 1080,
            "baseHeight": 1920,
            "outputWidth": 1080,
            "outputHeight": 1920,
        }
        self.item_transform: dict | None = None
        self.item_enabled: bool | None = None
        # What every screenshot contains; tests that look inside one set a real image.
        self.image = PNG

    def make_client(self) -> "FakeClient":
        return FakeClient(self)

    def calls(self, request_type: str) -> list[dict | None]:
        return [data for name, data in self.requests if name == request_type]

    def handle(self, request_type: str, data: dict | None) -> dict:
        self.requests.append((request_type, data))
        match request_type:
            case "GetCurrentProgramScene":
                return {"currentProgramSceneName": "Scene 1"}
            case "GetSceneItemList":
                return {"sceneItems": self.scene_items}
            case "GetSourceScreenshot":
                return {"imageData": "data:image/png;base64," + base64.b64encode(self.image).decode()}
            case "SaveSourceScreenshot":
                # Like OBS, the file exists by the time the request succeeds.
                Path(data["imageFilePath"]).write_bytes(self.image)
            case "GetRecordStatus":
                return {"outputActive": self.recording, "outputPath": "C:/rec/a.mkv"}
            case "StartRecord":
                self.recording = True
            case "StopRecord":
                self.recording = False
                return {"outputPath": "C:/rec/a.mkv"}
            case "GetInputPropertiesListPropertyItems":
                items = [{"itemName": "", "itemValue": "", "itemEnabled": True}]
                items += [
                    {"itemName": f"[app.exe]: {value.split(':')[0]}", "itemValue": value}
                    for value in self.windows
                ]
                return {"propertyItems": items}
            case "SetInputSettings":
                self.window = data["inputSettings"]["window"]
                self.stale_remaining = self.stale_polls
            case "GetSceneItemTransform":
                if getattr(self, "stale_remaining", 0) > 0:
                    self.stale_remaining -= 1  # still the previous window's size
                else:
                    self.reported_size = self.windows.get(self.window, (0, 0))
                width, height = self.reported_size
                return {"sceneItemTransform": {"sourceWidth": width, "sourceHeight": height}}
            case "GetVideoSettings":
                return dict(self.video)
            case "SetVideoSettings":
                self.video.update(data)
            case "SetSceneItemTransform":
                self.item_transform = data["sceneItemTransform"]
            case "SetSceneItemEnabled":
                self.item_enabled = data["sceneItemEnabled"]
            case "CreateInput":
                self.input_names.add(data["inputName"])
                self.scene_items.append(scene_item(data["inputName"], item_id=7))
                return {"sceneItemId": 7}
            case "CreateSceneItem":
                self.scene_items.append(scene_item(data["sourceName"], item_id=8))
                return {"sceneItemId": 8}
        return {}


class FakeClient:
    """The subset of simpleobsws.WebSocketClient the app uses."""

    def __init__(self, obs: FakeObs) -> None:
        self._obs = obs
        self._identified = False

    async def connect(self) -> bool:
        if not self._obs.accepting:
            raise ConnectionRefusedError
        return True

    async def wait_until_identified(self, timeout: int = 10) -> bool:
        self._identified = self._obs.accepting
        return self._identified

    async def disconnect(self) -> bool:
        self._identified = False
        return True

    def is_identified(self) -> bool:
        return self._identified

    async def call(self, request, timeout: int = 15):
        obs = self._obs
        comment = obs.rejected.get(request.requestType)
        if request.requestType == "CreateInput" and request.requestData["inputName"] in obs.input_names:
            comment, obs.reject_codes["CreateInput"] = "Input already exists", 601
        if comment:
            code = obs.reject_codes.get(request.requestType, 600)
            status = SimpleNamespace(result=False, code=code, comment=comment)
            obs.requests.append((request.requestType, request.requestData))
            return SimpleNamespace(ok=lambda: False, requestStatus=status, responseData=None)
        data = obs.handle(request.requestType, request.requestData)
        status = SimpleNamespace(result=True, code=100, comment=None)
        return SimpleNamespace(ok=lambda: True, requestStatus=status, responseData=data)
