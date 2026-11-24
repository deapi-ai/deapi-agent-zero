"""Agent Zero tool: list deAPI tools and their arguments."""

from helpers.tool import Response, Tool
from usr.plugins.deapi.helpers.client import DeapiError, list_tools


class DeapiTools(Tool):
    async def execute(self, query="", **kwargs) -> Response:
        try:
            return Response(message=await list_tools(query or ""), break_loop=False)
        except DeapiError as error:
            return Response(message=str(error), break_loop=False)
