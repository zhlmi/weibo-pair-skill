# 数据采集规范

本文档定义微博配对三种模式的数据采集流程、API 调用方式和缓存策略。

## 认证方式

### API Token（唯一方式）

在微博开放平台控制台获取 API Token（`wb_` 开头，长期有效），写入环境变量：

```bash
export WEIBO_CLI_TOKEN="<your_api_token>"
```

所有 CLI API 调用统一使用 `Authorization: Bearer ${WEIBO_CLI_TOKEN}`。

> ⚠️ 设备码流程已废弃（2026-08-05 起），不再使用。不要尝试设备码、refresh token 轮换或 `weibo auth login`。

## 通用规则

1. **Token 管理**：weibo-skill 和 weibo-cli 各自管理 Token，不要在 Skill 中硬编码。
2. **CLI 调用方式**：直接使用 `weibo-cli` 命令。⚠️ iSH 环境下 weibo-cli 曾因自带 undici 6.x 与 iSH 网络栈不兼容而报 `fetch failed [NETWORK_ERROR]`，已通过替换为 undici 8.7.0 修复（见每日日志 2026-08-05）。若更新 CLI 后网络又挂，优先检查 undici 版本是否被降回 6.x。备份在 `node_modules/undici-6.27.0.bak`。
3. **子进程调用**：Python 脚本中调用 weibo-cli 时，`subprocess.run` 必须继承 `os.environ`（Token 在环境变量 `WEIBO_CLI_TOKEN`），不能用自定义 env 覆盖；可加 `env["NODE_OPTIONS"] = ""` 避免冲突。
4. **时间格式**：CLI 返回的 `created_at` 格式为 `'Tue Aug 04 14:43:06 +0800 2026'`，用 `datetime.strptime(s, '%a %b %d %H:%M:%S +0800 %Y')` 解析。
5. **分页策略**：
   - 每页最大 `count=20`（不是 100；`friends/biz` 实测 count 上限也是 20，尽管 --help 写 200）
   - `page` 参数只能翻 25 页（500 条），之后返回空或报错
   - 超过 25 页必须用 `max_id` 分页：取上一页最后一条的 `id` 作为 `max_id` 参数
   - `max_id` 是包含性的（返回 ID ≤ 该值的微博），需去重
6. **缓存策略**：同一目标用户的数据在同一次会话中缓存，不重复调用。跨会话断点缓存（pair.py 已内置）：
   - 对方微博 → `<缓存目录>/pair_other_posts.json`
   - 我方微博 → `<缓存目录>/pair_my_posts_<我方UID>.json`
   - 关注列表 → `<缓存目录>/pair_my_following_<登录UID>.json`（约 200 人，圈子兼容与互关检测共用）
   - 活跃关注样本 → `<缓存目录>/pair_active_users_<对方UID>.json`
   - 登录 UID → `<缓存目录>/pair_login_uid.json`（A×B 场景判定用）
   - 缓存命中条件：已有条数 ≥ 目标的 90% 直接复用；不足 90% 从缓存末尾 `max_id` **断点续传**（v1.5.0 起真实实现：`fetch_timeline(resume_from=...)`，中途限流/失败时已抓数据自动落盘，重跑自动续，不重头烧调用）。
7. **A×B 配对（v1.5.0）**：`--my-uid` 传非登录用户时（帮任意两人配对），脚本自动检测登录 UID（`users/show/biz`，结果缓存）并降级：
   - A 方微博改走 CLI `user_timeline/other`（`user_timeline/biz` 与 weibo-skill 只能操作登录用户本人——v1.4.x 曾静默拉错人）；
   - 圈子兼容降级为**内容圈层近似**（双方话题分布余弦），关注列表/UID 交集不可得（`friends/biz` 仅登录用户）；
   - 互关自动检测标注"API 受限"，可用 `--mutual-follow` 人工确认；
   - 费用：A、B 双方均按 CLI 调用计费。
8. **错误处理**：API 调用失败时，记录失败原因，跳过该维度继续分析，最终报告中标注缺失维度。
8. **采样策略**：默认使用标准深度，用户可要求深度分析（消耗更多 Credits）。
9. **采集顺序（双人配对硬性规则）**：**先采对方数据，后采我方数据**。原因：对方只能走付费 CLI（每页 20 条，300 条 ≈ 16 次调用），我方 100 条可走 weibo-skill 免费接口、完全不占 CLI 限流窗口。先采对方并立即落盘，即使触发限流也有缓存兜底；我方随时可补。反之若先采我方，一旦限流对方数据全丢，重拉再次烧掉 16+ 次调用。
10. **限流窗口**：CLI 读取接口限制 **60 次/小时，整点重置**（如 18:00、19:00 整点清空）。报错为 `TOO_MANY_REQUESTS`。规划调用时按整点对齐：剩余额度不足时，等整点重置后一次性跑完比零散重试更省。

## 数据源映射

| 数据类型 | 来源 | API 端点 | 说明 |
|---------|------|---------|------|
| 我的微博列表 | weibo-skill | `node scripts/weibo-skill.js status --count=100` | 上限 100 条，免费 |
| 我的微博列表（全量） | CLI | `POST /cli/invoke {"group":"statuses","action":"user_timeline/biz"}` | 需分页，数据在 `result.statuses` |
| 我发出的评论 | CLI | `POST /cli/invoke {"group":"comments","action":"by_me/biz"}` | 数据在 `result.comments` |
| @我的微博 | CLI | `POST /cli/invoke {"group":"statuses","action":"mentions/biz"}` | 数据在 `result.statuses` |
| @我的评论 | CLI | `POST /cli/invoke {"group":"comments","action":"to_me/biz"}` | 数据在 `result.comments` |
| 我的关注列表 | CLI | `POST /cli/invoke {"group":"friendships","action":"friends/biz"}` | 需验证参数 |
| 目标用户资料 | CLI | `POST /cli/invoke {"group":"users","action":"show_batch/other"}` | 通过昵称或 UID 查找 |
| 目标用户微博列表 | CLI | `POST /cli/invoke {"group":"statuses","action":"user_timeline/other"}` | 别人的发帖历史 |
| 目标用户关注列表 | ❌ 不可用 | `friends/other` 命令不存在（仅 `friends/biz` 可查自己） | 使用降级策略，见下文「活跃关注降级」 |
| 关键词搜索 | CLI | `POST /cli/invoke {"group":"search","action":"statuses/limited"}` | 按关键词搜微博 |

## 模式一：自画像数据采集

### 免费方案（weibo-skill）

```bash
node scripts/weibo-skill.js status --count=100        # 最多 100 条
node scripts/weibo-skill.js interactive-comments-to-me # 收到的评论
```
API 调用量：2 次（免费，无 Credits 消耗）

### CLI 增强方案（旗舰版）

```python
# 拉取微博（用 max_id 分页持续翻页）
all_posts = []
max_id = None
while len(all_posts) < target_count:
    args = {"count": "20"}
    if max_id: args["max_id"] = str(max_id)
    result = invoke("statuses", "user_timeline/biz", args)
    posts = result["result"]["statuses"]
    if not posts: break
    all_posts.extend(posts)
    max_id = posts[-1]["id"]
```
推荐拉取量：1,500+ 条（覆盖 3-6 个月，足够准确）

补充拉取：
- `comments/by_me/biz`（我发出的评论）
- `statuses/mentions/biz`（@我的）
- `comments/to_me/biz`（@我的评论）

API 调用量：~60-80 次（旗舰版免费）

## 模式二：双人透视数据采集

### 我方数据

同模式一的免费方案或 CLI 增强方案。

### 对方数据

```python
# 1. 找到对方 UID
invoke("users", "show_batch/other", {"screen_name": nickname})

# 2. 对方微博（用 max_id 分页）
invoke("statuses", "user_timeline/other", {"uid": uid, "count": "20"})

# 3. 对方关注列表 → ❌ friends/other 不存在，使用降级策略
#    一键脚本：scripts/active-following.py
#    python3 scripts/active-following.py --uid <对方UID> --count 100 --my-uid <我方UID> --output json
```

### 活跃关注降级（对方关注列表不可用时的替代）

> ⚠️ 官方 `friendships friends/other` 接口不存在，只能查自己的关注列表（`friends/biz`）。
> 因此用「对方微博中的转发来源 + @过的账号」作为对方"活跃关注"的近似样本，
> 对原创型博主（转发少/@少）补充「正文高频提及词」作为内容圈层信号。

**降级链路**（已实现为 `scripts/active-following.py`，实测通过）：

```
拉对方微博（user_timeline/other，官方接口 ✅）
  → 提取他转发过的账号（retweeted_status 里的来源用户，零额外调用）
  → 提取他 @ 过的账号（文本正则，show_batch/other 批量查详情，每批 ≤50）
  → 合并去重 → "活跃关注"近似样本
  → 品类归类（screen_name + description + domain + url 关键词）
  → 正文高频提及词 → 内容圈层品类分布（原创型博主主信号）
  → 圈子兼容对比（--my-uid）：
      a. UID 硬交集：我方关注列表 ∩ 对方活跃关注
      b. 品类相似度：我方关注列表品类分布 vs 对方活跃关注品类分布
      得分 = max(a, b)，标注降级方法
```

**已知限制**（实测 2026-08-05）：
- `other` 接口返回的 user 对象 `description` 字段被裁剪为空（隐私保护），`show_batch/other` 也补不回来 → 活跃关注样本的品类归类置信度低，大量落在"未知"，此时以**内容圈层**（正文提及词）为主信号
- 原创型博主转发少（实测 114 条仅 2 个唯一转发来源）→ 活跃关注样本量小，UID 硬交集可能为 0，以品类相似度兜底
- 品类归类会**过滤掉对方本人**（转发的第一条来源常是本人）

**调用成本**：转发来源零额外调用；@账号按每批 50 个 show_batch；圈子兼容需要 1 次 friends/biz（count=20）。总计比直接拉关注列表更省（实测整条链路 ~7 次调用 ≈ 5-7 Credits）。

### 双方互动数据

```python
# 在 @我的列表中筛选对方
my_mentions = invoke("statuses", "mentions/biz")
# → 过滤 mention 中包含对方昵称的条目
```

## 模式三：关注列表定律数据采集

关注列表定律**不需要**拉取目标用户的微博列表。只需要关注列表 + 大V画像。

### 为什么只看大V

普通人的关注列表中，大部分是素人号——简介为空或写"微博爱好者"，无法判断领域。只有大V（万粉以上、有认证、有清晰简介）才能准确归类。核心假设：一个人关注了哪些领域的大V，就暴露了信息偏好。

### 分析深度控制

| 深度 | 拉取关注数 | 筛选大V | API 调用量 | 说明 |
|------|----------|---------|----------|------|
| 快扫 | 前 100 个 | 自动筛大V（万粉以上） | ~5 次 | 只看关注结构 |
| 标准 | 前 200 个 | 大V + 批量查详情 | ~10 次 | 推荐，BASIC 可用 |
| 深度 | 全量 | 全部大V + 细分品类 | ~20 次 | Plus+ 套餐 |

### 标准深度采集流程

```python
# 1. 获取关注列表
friends = invoke("friendships", "friends/biz", {"uid": target_uid})

# 2. 筛选大V：followers_count > 10000 或 verified = true
big_vs = [f for f in friends if f.get("followers_count", 0) > 10000 or f.get("verified")]

# 3. 批量查询大V详情（每批最多 50 个 UID）
uids = [v["id"] for v in big_vs]
invoke("users", "show_batch/other", {"uids": ",".join(uids[:50])})

# 4. 基于简介 + 认证类型 + 粉丝量级归类领域
# → 品类分布 → 认证类型分布 → 粉丝量级分布 → 多样性评分
```

### 不需要做的事情

- ❌ 不需要拉目标的微博列表
- ❌ 不需要采样关注账号的微博内容
- ❌ 不需要分析素人号（简介为空或信号不足）

## Token 管理（2026-08-05 起）

- 设备码流程已废弃，**不要**尝试设备码、refresh token 轮换或 `weibo auth login`。
- 唯一方式：微博开放平台控制台获取 `wb_` 开头长期 Token → 写入环境变量 `WEIBO_CLI_TOKEN`。
- Token 由 weibo-cli 自行读取环境变量，脚本无需管理；子进程调用继承 `os.environ` 即可。

## 错误处理

| 错误类型 | 处理方式 |
|---------|---------|
| `Parameter count must not exceed 20` | 将 count 设为 20 |
| `TOO_MANY_REQUESTS` | 限流：60 次读取/小时，**整点重置**。已抓数据自动落盘，中断后重跑断点续传；数据不足目标时按 `--on-short` 策略处理（ask=询问用户，非交互退出码 3；continue=用现有数据继续；abort=中止退出码 2） |
| `Token expired or invalid` | 确认 `WEIBO_CLI_TOKEN` 环境变量已设置且未过期（可在开放平台控制台检查） |
| `result.statuses` 为空 | 分页到底，正常停止 |
| 重复数据（`max_id` 分页含重复） | 用 `seen_ids` 集合去重 |
| 网络错误 | 重试 3 次，间隔递增（1s/2s/4s）；若 `fetch failed [NETWORK_ERROR]` 且 curl 正常，检查 undici 版本（见通用规则 2） |
