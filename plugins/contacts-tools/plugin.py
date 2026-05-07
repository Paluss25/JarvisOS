from __future__ import annotations

from plugin_runtime.tools import ToolSpec


def register(context):
    from agent_runner.tools import contacts_client

    return [
        ToolSpec(
            name="contacts_list",
            description="List all contacts in Radicale.",
            schema={"addressbook": {"type": "string", "default": ""}},
            handler=contacts_client.contacts_list,
        ),
        ToolSpec(
            name="contacts_search",
            description="Search contacts by name or email.",
            schema={"query": str, "addressbook": {"type": "string", "default": ""}},
            handler=contacts_client.contacts_search,
        ),
        ToolSpec(
            name="contacts_get",
            description="Get a specific contact by UID.",
            schema={"uid": str, "addressbook": {"type": "string", "default": ""}},
            handler=contacts_client.contacts_get,
        ),
        ToolSpec(
            name="contacts_update",
            description="Update a contact by UID after confirmation gate.",
            schema={
                "uid": str,
                "fn": str,
                "email": {"type": "string", "default": ""},
                "tel": {"type": "string", "default": ""},
                "note": {"type": "string", "default": ""},
                "addressbook": {"type": "string", "default": ""},
                "confirmed": {"type": "boolean", "default": False},
            },
            handler=contacts_client.contacts_update,
        ),
        ToolSpec(
            name="contacts_delete",
            description="Delete a contact by UID after confirmation gate.",
            schema={"uid": str, "addressbook": {"type": "string", "default": ""}, "confirmed": {"type": "boolean", "default": False}},
            handler=contacts_client.contacts_delete,
        ),
    ]
