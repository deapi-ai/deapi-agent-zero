### deapi_tools
List the deAPI tools and their arguments. Call it before `deapi` when you are not sure of a tool's name or arguments.
Arguments: `query` (optional string): words that must all appear in the tool name or description, such as "transcription" or "image".
Example:
~~~json
{"tool_name":"deapi_tools","tool_args":{"query":"video"}}
~~~
