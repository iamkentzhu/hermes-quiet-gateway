"""
quiet-gateway plugin
====================
Suppress noisy lifecycle status messages that Hermes sends to the
messaging platform during agent execution:

  - ⏳ Retrying in 2.5s (attempt 1/3)...
  - ⚠️ API call failed (attempt 1/3)...
  - 🔌 Provider: custom  Model: ...
  - Primary model failed — switching to fallback: ...
  - Context: ▰▰▰▰ 100% to compaction
  - Context compaction approaching (threshold: 65% of window)

The final answer is always delivered normally.

Installation
------------
Drop this folder into ~/.hermes/plugins/quiet-gateway/ and restart:

    hermes gateway restart

Configuration (optional, in ~/.hermes/config.yaml)
---------------------------------------------------
plugins:
  quiet_gateway:
    # status_mode controls lifecycle message visibility:
    #   quiet   (default) — suppress all lifecycle noise, only final answer reaches the platform
    #   verbose           — pass all lifecycle messages through unfiltered (debug mode)
    status_mode: quiet

    # Platforms to filter. Omit to filter all platforms.
    # Set to [] to disable without removing the plugin.
    platforms: [feishu, telegram, slack]

    # Extra suppress patterns (Python regex, case-insensitive).
    extra_suppress_patterns: []

    # Patterns to always allow through.
    allow_patterns: []

How it works
------------
Patches GatewayRunner._run_agent (gateway/run.py) to wrap the
status_callback assigned to each agent turn. The wrapper filters
matching lifecycle noise before it reaches the chat platform.

GatewayRunner is loaded before run_agent.py, so there's no circular
import issue.

Upgrade safety
--------------
User plugins in ~/.hermes/plugins/ are never touched by hermes upgrades.
If _run_agent signature changes, the plugin degrades safely.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import re
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in suppress patterns  (case-insensitive regex)
# ---------------------------------------------------------------------------

_BUILTIN_SUPPRESS_PATTERNS: List[str] = [
    # Retry backoff
    r"⏳\s*retrying in",
    r"retrying in\s+[\d.]+s",

    # API call failure notices
    r"⚠️\s+api call failed",
    r"🔌\s+provider:",
    r"🌐\s+endpoint:",
    r"📝\s+error:",
    r"⏱️\s+elapsed:",
    r"⚠️\s+max retries.*exhausted",

    # Model fallback / provider switching
    r"primary model failed",
    r"switching to fallback",
    r"🔄\s+primary model failed",
    r"falling back to",

    # Context compression progress
    r"context:\s*[▰▱█░]{2,}",
    r"context compaction",
    r"compaction approaching",
    r"to compaction",
    r"% of window",

    # Memory persistence notices
    r"💾\s+memory updated",
    r"memory updated",

    # Other system diagnostics
    r"truncated tool call",
    r"invalid api response",
    r"stripped all thinking blocks",
]

_patched = False


def _load_config() -> dict:
    try:
        from hermes_cli.config import load_config
        cfg = load_config()
        return cfg.get("plugins", {}).get("quiet_gateway", {}) or {}
    except Exception:
        return {}


def _build_filter(config: dict) -> Callable[[str], bool]:
    patterns = list(_BUILTIN_SUPPRESS_PATTERNS)
    for p in config.get("extra_suppress_patterns") or []:
        if p:
            patterns.append(str(p))

    try:
        suppress_re = re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
    except re.error as e:
        logger.warning("[quiet-gateway] Invalid suppress pattern: %s — filter disabled", e)
        return lambda msg: False

    allow_re: Optional[re.Pattern] = None
    allow_raw = [str(p) for p in (config.get("allow_patterns") or []) if p]
    if allow_raw:
        try:
            allow_re = re.compile("|".join(f"(?:{p})" for p in allow_raw), re.IGNORECASE)
        except re.error as e:
            logger.warning("[quiet-gateway] Invalid allow pattern: %s — ignoring", e)

    def _should_suppress(message: str) -> bool:
        if allow_re and allow_re.search(message):
            return False
        return bool(suppress_re.search(message))

    return _should_suppress


def _wrap_status_callback(
    original_cb: Callable,
    should_suppress: Callable[[str], bool],
    platform: str,
    enabled_platforms: Optional[List[str]],
) -> Callable:
    """Return a wrapped status_callback that drops matching messages."""

    @functools.wraps(original_cb)
    def _filtered(event_type: str, message: str) -> None:
        if enabled_platforms is not None and platform not in enabled_platforms:
            return original_cb(event_type, message)
        if should_suppress(message):
            logger.debug("[quiet-gateway] suppressed [%s] on %s: %.120s",
                         event_type, platform or "?", message)
            return
        return original_cb(event_type, message)

    return _filtered


def _patch_gateway_runner(config: dict) -> bool:
    """Patch GatewayRunner._run_agent to wrap the per-turn status_callback."""
    global _patched
    if _patched:
        return True

    try:
        from gateway.run import GatewayRunner  # type: ignore[import]
    except ImportError as e:
        logger.warning("[quiet-gateway] Cannot import GatewayRunner: %s", e)
        return False

    if getattr(GatewayRunner._run_agent, "_quiet_gateway_patched", False):
        _patched = True
        return True

    platforms_raw = config.get("platforms")
    enabled_platforms: Optional[List[str]] = None
    if isinstance(platforms_raw, list) and platforms_raw:
        enabled_platforms = [str(p).lower() for p in platforms_raw]

    should_suppress = _build_filter(config)
    original_run_agent = GatewayRunner._run_agent

    @functools.wraps(original_run_agent)
    async def _patched_run_agent(self_runner, *args, **kwargs):
        # Determine platform from 'source' argument
        # Signature: _run_agent(self, message, context_prompt, history, source, ...)
        source = kwargs.get("source") or (args[3] if len(args) > 3 else None)
        platform_val = ""
        if source is not None:
            p = getattr(source, "platform", None)
            if p is not None:
                platform_val = str(getattr(p, "value", p)).lower()

        # Run the original; then immediately wrap the agent's status_callback
        # The agent object is cached on self_runner — we need to intercept
        # before it processes the turn. We do this by temporarily wrapping
        # the _status_callback_sync assignment via a post-construction hook.
        #
        # Strategy: patch asyncio loop to intercept the run_in_executor call
        # that kicks off run_sync(), so we can wrap status_callback on the agent.
        # Simpler: override the agent's status_callback right after _run_agent
        # creates/fetches it from cache, using a threading hook on the agent class.

        # Inject a one-shot wrapper via a subclass trick on the cached agent.
        # We monkeypatch _run_agent's local by wrapping the *GatewayRunner* method
        # that assigns status_callback (line ~7920): agent.status_callback = _status_callback_sync
        # Since that's a closure we can't touch, we instead intercept at the
        # run_agent.AIAgent level — but using importlib to force a fresh lookup
        # AFTER run_agent is fully initialized.

        import sys
        import importlib

        run_agent_mod = sys.modules.get("run_agent")
        if run_agent_mod is not None:
            AIAgent = getattr(run_agent_mod, "AIAgent", None)
            if AIAgent is not None and not getattr(AIAgent._emit_status, "_quiet_gateway_patched", False):
                _patch_ai_agent_emit_status(AIAgent, should_suppress, enabled_platforms, platform_val)

        return await original_run_agent(self_runner, *args, **kwargs)

    _patched_run_agent._quiet_gateway_patched = True
    GatewayRunner._run_agent = _patched_run_agent  # type: ignore[method-assign]
    _patched = True

    logger.info(
        "[quiet-gateway] Patched GatewayRunner._run_agent%s",
        f" — filtering platforms: {enabled_platforms}" if enabled_platforms else " — filtering all platforms",
    )
    return True


def _patch_ai_agent_emit_status(
    AIAgent,
    should_suppress: Callable[[str], bool],
    enabled_platforms: Optional[List[str]],
    hint_platform: str,
) -> None:
    """Patch AIAgent._emit_status once we have the fully-initialized class."""
    original = AIAgent._emit_status

    @functools.wraps(original)
    def _filtered(self_agent, message: str) -> None:
        platform = str(getattr(self_agent, "platform", "") or hint_platform or "").lower()

        if enabled_platforms is not None and platform not in enabled_platforms:
            return original(self_agent, message)

        if should_suppress(message):
            logger.debug("[quiet-gateway] suppressed on %s: %.120s", platform or "?", message)
            try:
                self_agent._vprint(
                    f"{getattr(self_agent, 'log_prefix', '')}[quiet-gw] {message}"
                )
            except Exception:
                pass
            return

        return original(self_agent, message)

    _filtered._quiet_gateway_patched = True
    AIAgent._emit_status = _filtered  # type: ignore[method-assign]
    logger.info("[quiet-gateway] Patched AIAgent._emit_status — lifecycle noise suppressed")


def register(ctx) -> None:
    """Hermes plugin entry point."""
    config = _load_config()

    platforms_raw = config.get("platforms")
    if isinstance(platforms_raw, list) and len(platforms_raw) == 0:
        logger.info("[quiet-gateway] Disabled via config (platforms: [])")
        return

    # status_mode: quiet (default, suppress all) | verbose (pass all through)
    mode = str(config.get("status_mode") or "quiet").lower()
    if mode == "verbose":
        logger.info("[quiet-gateway] status_mode=verbose — lifecycle messages will pass through unfiltered")
        return

    ok = _patch_gateway_runner(config)
    if not ok:
        logger.warning("[quiet-gateway] Failed to patch GatewayRunner — plugin inactive")
    else:
        logger.info("[quiet-gateway] Registered (status_mode=quiet) — will suppress lifecycle noise on next turn")
