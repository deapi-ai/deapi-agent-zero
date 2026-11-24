"""Agent Zero tool: run one deAPI tool (image, video, speech, music, transcription, OCR)."""

from helpers.tool import Response, Tool
from usr.plugins.deapi.helpers.client import DeapiError, call_tool


class Deapi(Tool):
    async def execute(self, tool="", arguments=None, **kwargs) -> Response:
        if kwargs:
            return Response(
                message="deapi takes only 'tool' and 'arguments'. Put the deAPI tool's "
                "own parameters inside 'arguments'.",
                break_loop=False,
            )
        await self.set_progress(f"deAPI: running {tool}…")
        try:
            return Response(message=await call_tool(tool, arguments), break_loop=False)
        except DeapiError as error:
            return Response(message=str(error), break_loop=False)
