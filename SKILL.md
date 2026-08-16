---
name: weibo-pair
description: |
  微博配对——看清自己，也看清你和 TA 的合拍度。
  免费入口：自画像（用 weibo-skill 就能跑，零门槛）。
  付费入口：双人配对（情侣/朋友/商务三种方向，需要 CLI）。
  触发词：配对、看配不配、合不合、自画像、相亲、缘分指数。
metadata:
  version: "1.8.2"
---

# 微博配对

> 自画像给你自信，配对检验你的自信。

- **自画像**（免费）：看自己——微博暴露了怎样的你。`scripts/self-portrait.py`
- **双人配对**（付费，需 CLI）：看你和 TA 的合拍度。`scripts/pair.py`

## 资源路由

| 文件 | 何时读 | 内容 |
|------|--------|------|
| `references/data-sources.md` | 执行前 | 采集规范：API、参数、缓存、限流窗口 |
| `references/analysis-engine.md` | 采集后 | 分析维度、评分算法 |
| `references/self-portrait.md` | 自画像 | 面相术语映射、判词规则 |
| `references/matchmaking.md` | 双人配对 | 匹配维度、缘分算法（密度归一/极性） |
| `references/visual-output.md` | 输出前 | 模板规范、视觉风格 |
| `references/credit-optimization.md` | 规划调用 | Credits 策略、采样深度 |
| `scripts/pair.py` | 双人配对主流程 | 采集→分析→缘分→文案→渲染（196 行） |
| `scripts/self-portrait.py` | 自画像主流程 | 采集→七维→面相→判词→HTML |
| `scripts/config.py` | 配置 | 参数解析（`config.parse()`）+ 上下文 C |
| `scripts/weibo_api.py` | 数据获取 | cli/登录/采集/断点续传/缓存 |
| `scripts/analysis.py` | 分析 | 七维/圈子/缘分/密度归一 |
| `scripts/lexicons.py` | 词表（零依赖） | 话题/品类/极性/技术关键词 |
| `scripts/copywriter.py` | 文案 | 判词/点评/缘分徽章（prepare 读写 config.C） |
| `scripts/render.py` | 渲染 | 三模板 V 组装 |
| `scripts/active-following.py` | 圈子降级 | 活跃关注采样→圈子兼容 |
| `templates/couple.html` | 情侣模板 | 相亲角报纸风 |
| `templates/business.html` | 商务模板 | 数据杂志风（Swiss） |
| `templates/friend.html` | 朋友模板 | 电影片尾风（电平表） |
| `templates/portrait.html` | 自画像模板 | 面相诊断书风 |
| `templates/mingpan.html` | 自画像模板 | 星空罗盘动效版 |

## 前置条件

1. **weibo-skill**（我方 ≤100 条免费）：登录 `node weibo-skill.js login --app-id=<ID> --app-secret=<SECRET>`（凭证获取私信 @微博龙虾助手 发"连接龙虾"）。
2. **weibo-cli**（对方数据，¥29/月起）：`npm i -g @weibo-ai/weibo-cli`；**iSH 必须替换 undici 8.7.0**（否则 `fetch failed`），步骤见 data-sources.md。
3. **环境变量**：`WEIBO_CLI_TOKEN`（`wb_` 开头，必填）。
4. **自检（入口 Step 0 实际执行）**：`weibo-cli doctor` 全 ✓ / Token 已设 / `weibo-skill status` 可拉数据。

## 两种模式

- 🔮 **自画像**：`python3 scripts/self-portrait.py [--count 100] [--output 面相.html] [--template portrait|mingpan] [--on-short ask|continue|abort]`——七维→面相术语→判词→诊断书/星盘 HTML。
- 💑 **双人配对**：`python3 scripts/pair.py --other-uid <UID> --my-uid <UID> --count 100 [--mode couple|friend|business] [--output 报告.html] [--my-nick/--other-nick/--my-role/--other-role] [--mutual-follow] [--polarity-note <关系事实>] [--on-short ask|continue|abort]`。

## 🔴 入口红灯（一次性收集，收集完不再确认）

**Step 0 · 前置自检**（先跑通再继续）：doctor / Token / weibo-skill status。

**Step 1 · 模式**：
```
① 🔮 自画像（免费，weibo-skill）
② 💑 双人配对（CLI，见费用表）
```
- 🔴 停止等用户选。

**费用（按量付费，官方口径见 open.weibo.com/cli，以 `weibo-cli doctor` / `weibo-cli me` 为准）**：2026-08 官方套餐体系改版后，接口不再按套餐档位锁定——开通服务（formal_active）后全部 67 个接口全量开放，按 Credits 按量计费，余额以 `weibo-cli me` 的 Credits 为准。

**Step 2 · 对象与关系背景**：
- 自画像：无需对象。
- 双人配对：对方 UID/昵称（A×B 场景——两人都非本人——需提供双 UID，双方均走 CLI 均计费）。
- **关系背景（推荐，直接影响判词）**：互关用 `--mutual-follow`、关系性质用 `--polarity-note`（如"线下老朋友"）——用户事实优先于自动判定，先问再跑防返工。

**Step 3 · 方向（双人配对）**：`couple` 情侣（相亲角）· `friend` 朋友（片尾，默认）· `business` 商务（数据杂志）。🔴 停止等用户选。

**Step 4 · 数据量**（自画像或对方；我方本人默认 100 免费）：
```
⚡ 50~100 条（~3-6 次调用）  📊 200~500 条（~10-30 次）  🔬 800+ 条（40+ 次，超窗口）
🎚 自定义：每 20 条 = 1 次调用
```
- ⚠️ **限流**：CLI 60 次/小时、**整点重置**。800+ 条需跨整点两段跑（断点续传自动）。

**Step 5 · 输出模板（自画像）**：`portrait` 面相诊断书（默认）· `mingpan` 星空罗盘动效。🔴 停止等用户选。

## 执行

**自画像**：`self-portrait.py`（采集→七维→面相→渲染）。数据不足按 `--on-short`：ask 询问（默认，非交互退出码 3）/ continue / abort。

**双人配对**：
1. **先采对方后采我方**（硬性顺序，抗限流）：对方走 CLI 优先落盘；我方 ≤100 走 weibo-skill 免费。
2. 断点续传：中断自动落盘，重跑从缓存 max_id 续传，不重头烧调用。
3. 数据不足按 `--on-short` 询问用户，不静默出报告。
4. 采集顺序 / 圈子降级 / 缘分算法细节见 `references/data-sources.md` 与 `matchmaking.md`。

**缓存**（`/var/minis/workspace/`，均按 UID 隔离）：对方 `pair_other_posts_<UID>.json`、我方 `pair_my_posts_<UID>.json`、关注 `pair_my_following_<登录UID>.json`、活跃样本 `pair_active_users_<UID>.json`、登录 `pair_login_uid.json`。

## 圈子背景（解读圈子兼容与缘分的前提）

- **算法校准语境（示例）**：本 Skill 的缘分/圈子算法在数字影像、色彩科学等**技术圈**校准——该圈层转发克制，只互转核心文献与技术内容，常无文字纯转发。
- **技术圈转发克制**：出现"直接转发/共现"含金量高于泛娱乐圈同等行为。
- **算法落点**：直接转发权重最高（0.45/次）；共现技术内容加权（×1.5）；圈子兼容含「影像」品类。

## 风险纪律

1. 不对真实个人实施侮辱、造谣或可识别的人身攻击。2. 定位为"社交行为模式观察"，非人格鉴定。3. 建议保持荒诞幽默，不涉真实情感建议。4. 基于公开数据，不涉隐私。5. 输出不暴露 UID 等可识别信息。6. 分析他人需用户明确提供 UID 并确认。

## 交付原则

- HTML 模板渲染视觉输出；同输出结构化数据（JSON）与创意判词。
- 速度优先：默认采样分析，可要求深度。
- 每个模式附分享文案与互动引导。
