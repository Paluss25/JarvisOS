"""SDK hook builders — create all hook matchers from workspace_path."""

from pathlib import Path


def build_all_hooks(
    workspace_path: Path,
    extra_tool_labels: dict[str, str] | None = None,
) -> dict:
    """Return the full hooks dict for ClaudeAgentOptions.

    Args:
        workspace_path: Agent workspace root (used for daily memory log).
        extra_tool_labels: Agent-specific tool → human label mappings merged
            on top of the default set in permission_hook._BASE_TOOL_LABELS.
    """
    from agent_runner.hooks.permission_hook import (
        build_pre_tool_use_matchers,
        build_notification_matchers,
        build_post_tool_use_matchers,
        build_post_tool_use_failure_matchers,
        build_stop_matchers,
        build_subagent_start_matchers,
        build_subagent_stop_matchers,
        build_user_prompt_submit_matchers,
        build_pre_compact_matchers,
    )
    return {
        "PreToolUse":            build_pre_tool_use_matchers(workspace_path, extra_tool_labels),
        "Notification":          build_notification_matchers(),
        "PostToolUse":           build_post_tool_use_matchers(workspace_path),
        "PostToolUseFailure":    build_post_tool_use_failure_matchers(workspace_path),
        "Stop":                  build_stop_matchers(workspace_path),
        "SubagentStart":         build_subagent_start_matchers(workspace_path),
        "SubagentStop":          build_subagent_stop_matchers(workspace_path),
        "UserPromptSubmit":      build_user_prompt_submit_matchers(workspace_path),
        "PreCompact":            build_pre_compact_matchers(workspace_path),
    }
