# hermes-quiet-gateway

Silence noisy Hermes lifecycle messages so your chat platform only receives the final answer.

屏蔽 Hermes Agent 的中间状态噪音，让聊天平台只收到最终答案。

---

## What is this / 这是什么

A [Hermes Agent](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/feishu) plugin that intercepts lifecycle status messages before they reach your chat platform — retries, model fallbacks, context compression progress, and API errors all suppressed. The final answer always gets through.

[Hermes Agent](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/feishu) Hermes Agent官方的飞书插件，在生命周期状态消息到达聊天平台之前将其拦截——重试、模型切换、上下文压缩进度、API 报错全部屏蔽，只有最终答案正常送达。

---

## Before / After / 效果对比

**Before** — your chat fills up with system messages:

**安装前** — 聊天记录被系统消息淹没：

```
⏳ Retrying in 2.5s (attempt 1/3)...
⚠️ API call failed (attempt 2/3)...
🔄 Primary model failed — switching to fallback: openrouter/free
Context: ▰▰▰▰▰ 78% to compaction
⚠️ Max retries exhausted — trying fallback...
[final answer buried here]
```

**After** — only the final answer arrives.

**安装后** — 只有最终答案。

---

## Quick Install / 快速安装

```bash
curl -fsSL https://raw.githubusercontent.com/iamkentzhu/hermes-quiet-gateway/main/install.sh | bash
```

Restart your gateway after install:

安装后重启 gateway：

```bash
hermes gateway restart
```

> The installer also adds `quiet-gateway` to `plugins.enabled` in `~/.hermes/config.yaml`. Hermes plugins are **opt-in** — they only load when listed there. See [Opt-in requirement](#opt-in-requirement--opt-in-启用要求) below.
>
> 安装脚本会自动把 `quiet-gateway` 加到 `~/.hermes/config.yaml` 的 `plugins.enabled`。Hermes 插件是 **opt-in** —— 未出现在这个列表里的插件不会被加载。详见下文 [Opt-in 启用要求](#opt-in-requirement--opt-in-启用要求)。

---

## Opt-in requirement / Opt-in 启用要求

Hermes loads **only** plugins listed under `plugins.enabled` in `~/.hermes/config.yaml`. If the key is missing or empty, nothing loads — you won't see any errors, the plugin is simply ignored.

Hermes 只加载 `~/.hermes/config.yaml` 中 `plugins.enabled` 列表里的插件。如果这个字段缺失或为空，插件会被静默忽略，**不会有任何报错**。

The installer adds `quiet-gateway` automatically. If you install by hand, or if your config gets reset / migrated, make sure it's there:

安装脚本会自动添加；如果你是手动安装，或 config 被重置/迁移，请确认配置里有这一段：

```yaml
# ~/.hermes/config.yaml
plugins:
  enabled:
  - quiet-gateway
```

**Verify after restart / 重启后验证：**

```bash
grep quiet-gateway ~/.hermes/logs/agent.log | tail -3
# Expected / 应该看到:
# [quiet-gateway] Patched GatewayRunner._run_agent — filtering all platforms
# [quiet-gateway] Registered (status_mode=quiet) — will suppress lifecycle noise on next turn
```

If you don't see these lines, the plugin is not being loaded — re-check `plugins.enabled`.

如果没有这些日志，说明插件没有加载 —— 请检查 `plugins.enabled` 配置。

---

## Modes / 两种模式

| Mode / 模式 | Behavior / 行为 |
|---|---|
| `quiet` **(default / 默认)** | All lifecycle noise suppressed — only the final answer reaches the platform / 屏蔽所有中间噪音，只有最终答案到达平台 |
| `verbose` | All messages pass through unfiltered — for debugging / 所有消息原样透传，用于调试 |

Switch to verbose / 切换到 verbose 模式：

```yaml
# ~/.hermes/config.yaml
plugins:
  quiet_gateway:
    status_mode: verbose   # quiet (default) | verbose
```

Switch back by removing the line or setting it to `quiet`. Restart gateway after any change.

改回静默：删掉这行或改成 `quiet`。修改后需重启 gateway。

---

## How it works / 工作原理

The plugin patches `AIAgent._emit_status` — the single method responsible for all lifecycle messages in Hermes — to intercept messages before they reach the chat adapter.

插件通过 monkeypatch 拦截 `AIAgent._emit_status`——Hermes 中所有 lifecycle 消息的唯一出口——在消息到达聊天 adapter 之前将其过滤掉。

To avoid circular import issues at plugin load time, the patch is applied lazily: it wraps `GatewayRunner._run_agent` first (safe to import at load time), then patches `AIAgent._emit_status` on the first agent turn once `run_agent` is fully initialized in `sys.modules`.

为避免插件加载时的循环 import 问题，patch 采用懒加载策略：先 wrap `GatewayRunner._run_agent`（加载时安全），在第一次 agent turn 时再 patch `AIAgent._emit_status`（此时 `run_agent` 已完全初始化）。

Suppressed messages are not lost — they are still printed locally via `_vprint` so you can see them in the terminal.

被屏蔽的消息不会丢失，仍通过 `_vprint` 在本地终端输出。

---

## Hermes upgrades / Hermes 升级的影响

User plugins in `~/.hermes/plugins/` are **never touched by Hermes upgrades** — the plugin survives upgrades automatically.

`~/.hermes/plugins/` 下的用户插件**不会被 Hermes 升级覆盖**，插件本身安全。

The only risk: if Hermes changes the internal signature of `AIAgent._emit_status` or `GatewayRunner._run_agent`, the plugin will log a warning and degrade gracefully — messages pass through unfiltered rather than crashing.

唯一风险：如果 Hermes 修改了 `AIAgent._emit_status` 或 `GatewayRunner._run_agent` 的内部签名，插件会打印 warning 并安全降级——消息原样透传，不会崩溃。

---

## Advanced configuration / 高级配置

```yaml
plugins:
  quiet_gateway:
    status_mode: quiet          # quiet (default) | verbose
    platforms: [feishu]         # filter specific platforms only; omit to filter all / 指定平台，省略则过滤全部
    extra_suppress_patterns: [] # additional regex patterns to suppress / 额外屏蔽规则（Python regex，大小写不敏感）
    allow_patterns: []          # patterns that always pass through / 强制放行规则，优先级高于屏蔽
```

---

## License

MIT © kent
