from plugin_runtime.tools import ToolSpec


def test_tool_spec_keeps_name_description_schema_and_handler():
    def handler(args):
        return {"ok": args["value"]}

    spec = ToolSpec(
        name="echo",
        description="Echo a value.",
        schema={"type": "object", "properties": {"value": {"type": "string"}}},
        handler=handler,
    )

    assert spec.name == "echo"
    assert spec.handler({"value": "x"}) == {"ok": "x"}
