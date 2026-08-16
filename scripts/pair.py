#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微博配对 · 主流程编排：采集 → 七维 → 圈子 → 缘分 → 文案 → 渲染。

模块划分：
  config.py      全局配置（参数 + 上下文）
  weibo_api.py   数据获取（cli/采集/缓存/断点续传）
  analysis.py    分析（词表/七维/圈子/缘分）
  copywriter.py  文案（判词/建议）
  render.py      渲染（三模板/V 组装）
"""
import json, os, sys, math, re, subprocess
from collections import Counter

import config
config.parse()          # 显式解析参数（weibo_api/analysis import config 无副作用）
import datetime, os, random
random.seed(int(datetime.datetime.now().timestamp() * 1_000_000) ^ os.getpid())  # 文案变体池高精度种子
import weibo_api
import analysis

# ================= 0. 登录检测 =================
LOGIN_UID = weibo_api.get_login_uid()
config.LOGIN_UID = LOGIN_UID
config.IS_SELF = (LOGIN_UID is None) or (str(config.MY_UID) == str(LOGIN_UID))
if not config.IS_SELF:
    print(f"  ℹ️ A×B 配对模式：A 方（UID {config.MY_UID}）非登录用户，我方数据改走 CLI user_timeline/other，"
          f"关注列表/互关检测受 API 限制将降级标注", file=sys.stderr)
config.FOLLOWING_CACHE = f"{config.CACHE_DIR}/pair_my_following_{LOGIN_UID or config.MY_UID}.json"

# ================= 1. 昵称 =================
if not config.MY_NICK or not config.OTHER_NICK:
    try:
        d = weibo_api.cli(["users", "show_batch/other", "--uids", f"{config.MY_UID},{config.OTHER_UID}", "--output", "json"])
        for u in (d.get("users") or []):
            if str(u.get("id")) == str(config.MY_UID) and not config.MY_NICK:
                config.MY_NICK = u.get("screen_name")
            if str(u.get("id")) == str(config.OTHER_UID) and not config.OTHER_NICK:
                config.OTHER_NICK = u.get("screen_name")
    except Exception as e:
        print(f"  ⚠️ 昵称自动获取失败: {str(e)[:100]}", file=sys.stderr)
config.MY_NICK = config.MY_NICK or f"用户{config.MY_UID}"
config.OTHER_NICK = config.OTHER_NICK or f"用户{config.OTHER_UID}"

# ================= 2. 采集对方 =================
config.OTHER_CACHE = f"{config.CACHE_DIR}/pair_other_posts_{config.OTHER_UID}.json"
config.MY_CACHE = f"{config.CACHE_DIR}/pair_my_posts_{config.MY_UID}.json"

print("== 采集对方微博 ==", file=sys.stderr)
other_posts = weibo_api.load_cache(config.OTHER_CACHE, config.COUNT)
if other_posts is not None:
    print(f"对方 {len(other_posts)} 条（命中缓存，跳过 API）", file=sys.stderr)
else:
    other_cached = weibo_api.load_cache(config.OTHER_CACHE, 1)  # 部分缓存 → 断点续传
    if other_cached:
        print(f"  断点续传：已有 {len(other_cached)} 条缓存，继续拉取", file=sys.stderr)
    other_posts = weibo_api.unpin(weibo_api.fetch_timeline(config.OTHER_UID, config.COUNT, resume_from=other_cached, label="对方"), "对方")
    json.dump(other_posts, open(config.OTHER_CACHE, "w"), ensure_ascii=False)
    print(f"对方 {len(other_posts)} 条", file=sys.stderr)
    weibo_api.confirm_short("对方", len(other_posts), config.COUNT)

# ================= 3. 采集我方 =================
print("== 采集我方微博 ==", file=sys.stderr)
my_posts = weibo_api.load_cache(config.MY_CACHE, config.MY_COUNT)
if my_posts is not None:
    print(f"我方 {len(my_posts)} 条（命中缓存，跳过 API）", file=sys.stderr)
elif (not config.IS_SELF) or config.MY_COUNT > 100:
    # A×B（A 方非登录用户）或超量：走 CLI。biz 仅限登录用户本人，A×B 用 user_timeline/other
    my_cached = weibo_api.load_cache(config.MY_CACHE, 1)
    if my_cached:
        print(f"  断点续传：已有 {len(my_cached)} 条缓存，继续拉取", file=sys.stderr)
    my_posts = weibo_api.unpin(weibo_api.fetch_timeline(config.MY_UID, config.MY_COUNT, own=config.IS_SELF, resume_from=my_cached, label="我方"), "我方")
    json.dump(my_posts, open(config.MY_CACHE, "w"), ensure_ascii=False)
    weibo_api.confirm_short("我方", len(my_posts), config.MY_COUNT)
else:
    # 本人 + ≤100 条：weibo-skill 免费快照（与已有部分缓存 merge，不覆盖丢数据）
    try:
        r = subprocess.run(["node", os.path.join(os.path.dirname(config.SKILL_DIR), "weibo-skill", "scripts", "weibo-skill.js"), "status", "--count=100"],
                           capture_output=True, text=True)
        my_raw = json.loads(r.stdout)
    except Exception as e:
        print(f"  ⚠️ weibo-skill 调用失败: {e}", file=sys.stderr)
        my_raw = {}
    snap = my_raw.get("data", {}).get("statuses", [])
    cached_posts = weibo_api.load_cache(config.MY_CACHE, 1) or []
    if cached_posts:
        _seen = {p.get("id") for p in cached_posts if p.get("id")}
        _added = 0
        for p in snap:
            if p.get("id") not in _seen:
                cached_posts.append(p); _added += 1
        print(f"  ℹ️ 已有部分缓存 {len(snap)}→merge 后 {len(cached_posts)} 条（新增 {_added}）", file=sys.stderr)
        my_posts = cached_posts
    else:
        my_posts = snap
    my_posts = weibo_api.unpin(my_posts, "我方")
    json.dump(my_posts, open(config.MY_CACHE, "w"), ensure_ascii=False)
    weibo_api.confirm_short("我方", len(my_posts), config.MY_COUNT)
if not my_posts:
    raise RuntimeError("我方微博采集为空：本人场景请检查 weibo-skill 登录；A×B 场景请检查 CLI 服务与 UID")
if not other_posts:
    raise RuntimeError("对方微博采集为空：请检查对方 UID 是否正确、服务是否已开通（A×B 场景双方均需 CLI）")
print(f"我方 {len(my_posts)} 条", file=sys.stderr)

# ================= 4. 七维分析 =================
A = analysis.seven_dimensions(my_posts, config.MY_NICK)
B = analysis.seven_dimensions(other_posts, config.OTHER_NICK)
print("\n== A 我方 ==", file=sys.stderr); print(json.dumps(A, ensure_ascii=False, indent=1), file=sys.stderr)
print("== B 对方 ==", file=sys.stderr); print(json.dumps(B, ensure_ascii=False, indent=1), file=sys.stderr)

# ================= 5. 圈子兼容（降级） =================
print("\n== 圈子兼容（降级） ==", file=sys.stderr)
config.ACTIVE_CACHE = f"{config.CACHE_DIR}/pair_active_users_{config.OTHER_UID}.json"
merged = weibo_api.load_cache(config.ACTIVE_CACHE, 1)  # 复用已采样的活跃关注样本
if merged is not None:
    print(f"活跃关注样本缓存命中: {len(merged)}", file=sys.stderr)
else:
    repost_users = []
    for p in other_posts:
        rt = p.get("retweeted_status")
        if rt and rt.get("user"): repost_users.append(rt["user"])
    mention_names = set()
    for p in other_posts:
        for m in re.findall(r"@([\w\u4e00-\u9fa5\-\.]+)", p.get("text", "")):
            mention_names.add(m)
    mention_users = []
    names = [n for n in mention_names if n not in {u.get("screen_name") for u in repost_users}]
    for i in range(0, len(names), 50):
        try:
            d = weibo_api.cli(["users", "show_batch/other", "--screen_name", ",".join(names[i:i + 50]), "--output", "json"])
            mention_users.extend(d.get("users") or [])
        except Exception as e:
            print(f"  ⚠️ @查询失败: {str(e)[:100]}", file=sys.stderr)
    merged, seen = [], set()
    for acc in repost_users + mention_users:
        k = acc.get("id") or acc.get("screen_name")
        if k and k not in seen:
            seen.add(k); merged.append(acc)
    merged = [a for a in merged if a.get("id") != config.OTHER_UID]
    json.dump(merged, open(config.ACTIVE_CACHE, "w"), ensure_ascii=False)
print(f"活跃关注样本: {len(merged)}", file=sys.stderr)

their_cat = Counter(analysis.categorize(a) for a in merged)
their_dist = {c: v / len(merged) for c, v in their_cat.items()} if merged else {}

# 我方关注列表（复用 load_following 缓存 200 人，不再直接 friends/biz 单页 20 人）
their_ids = {a.get("id") for a in merged if a.get("id")}
if config.IS_SELF:
    my_following, follow_src = weibo_api.load_following()
    if not my_following:
        my_following = []
        print("  ⚠️ 关注列表不可用（圈子兼容与互关检测降级）", file=sys.stderr)
    my_ids = {u.get("id") for u in my_following}
    my_cat = Counter(analysis.categorize(u) for u in my_following)
    my_dist = {c: v / len(my_following) for c, v in my_cat.items()} if my_following else {}
    inter = my_ids & their_ids
    overlap = len(inter) / len(their_ids) if their_ids else 0
else:
    # A×B：friends/biz 只能查登录用户自己，A 方关注列表不可得 → 圈子兼容降级为内容圈层近似
    my_following = []; my_ids = set(); inter = set(); overlap = 0.0; my_dist = {}
    print("  ⚠️ A×B 配对：A 方关注列表 API 不可得，圈子兼容以双方内容圈层（话题余弦）近似", file=sys.stderr)
keys = set(my_dist) | set(their_dist)
dot = sum(my_dist.get(k, 0) * their_dist.get(k, 0) for k in keys)
n1 = math.sqrt(sum(v * v for v in my_dist.values())); n2 = math.sqrt(sum(v * v for v in their_dist.values()))
cat_sim = dot / (n1 * n2) if n1 and n2 else 0
if not config.IS_SELF:
    cat_sim = round(analysis.cos(A["话题"]["dist"], B["话题"]["dist"]), 3)  # 内容圈层近似
circle = max(overlap, cat_sim)
print(f"UID交集: {len(inter)}/{len(their_ids)} = {overlap:.3f} | 品类相似度: {cat_sim:.3f} | 圈子兼容: {circle:.3f}", file=sys.stderr)

# ================= 6. 对比矩阵 + 缘分 + 总分 =================
ha, hb = A["作息"]["peak"], B["作息"]["peak"]
sleep, sleep_hits = analysis.sleep_score(A["作息"]["hours"], B["作息"]["hours"])
interest = round(analysis.cos(A["话题"]["dist"], B["话题"]["dist"]), 3)
personality = round(1 - abs(A["情绪"]["avg"] - B["情绪"]["avg"]), 3)
comm = 0.65  # 混合×混合
comp = round(min(0.5 + 0.5 * abs(A["创作"]["orig"] - B["创作"]["orig"]) + 0.2 * min(abs(A["作息"]["daily"] - B["作息"]["daily"]) / 10, 1), 0.95), 3)
humor = round(min(0.5 * (1 - abs(A["表达"]["ex"] - B["表达"]["ex"])) + (0.5 if (A["表达"]["ex"] < 0.1) != (B["表达"]["ex"] < 0.1) else 0.2), 0.9), 3)

fate, fate_sig, fate_details, follow_state, fate_polarity, fate_pos, fate_neg, fate_third, fate_density = analysis.scan_fate(
    my_posts, other_posts, config.MY_UID, config.MY_NICK, config.OTHER_UID, config.OTHER_NICK)
print(f"\n== 缘分指数 ==", file=sys.stderr)
print(f"  直接转发{fate_sig['direct_repost']} · 回复{fate_sig['reply']} · @提及{fate_sig['at']} · 转发链共现{fate_sig['chain'] + fate_sig['chain_tech']}（技术{fate_sig['chain_tech']}） · 互关{fate_sig['follow']}（状态:{follow_state}）→ 密度={fate_density}/百条 → fate={fate}", file=sys.stderr)
if fate_pos + fate_neg or fate_third:
    note = "（fate 已按极性调整）" if not config.POLARITY_NOTE else f"（{config.POLARITY_NOTE}，跳过极性打折）"
    print(f"  互动极性: 正面词{fate_pos} / 负面词{fate_neg} / 吐槽第三方{fate_third} → {fate_polarity}{note}", file=sys.stderr)
for d in fate_details[:6]:
    print(f"    - {d}", file=sys.stderr)

W = {"sleep": 0.15, "interest": 0.20, "personality": 0.20, "comm": 0.15, "comp": 0.10, "humor": 0.05, "circle": 0.05, "fate": 0.10}
scores = {"sleep": sleep, "interest": interest, "personality": personality, "comm": comm, "comp": comp, "humor": humor, "circle": circle, "fate": fate}
total = sum(scores[k] * W[k] for k in scores) * 100
print("\n== 得分 ==", file=sys.stderr)
for k in ["sleep", "interest", "personality", "comm", "comp", "humor", "circle", "fate"]:
    print(f"  {k}: {scores[k]:.3f}", file=sys.stderr)
print(f"  总分: {total:.1f}", file=sys.stderr)

# ================= 7. 文案 + 渲染 =================
config.C.update({
    "A": A, "B": B, "ha": ha, "hb": hb,
    "sleep": sleep, "interest": interest, "personality": personality, "comm": comm,
    "comp": comp, "humor": humor, "circle": circle, "fate": fate,
    "fate_sig": fate_sig, "follow_state": follow_state, "fate_polarity": fate_polarity,
    "fate_density": fate_density, "sleep_hits": sleep_hits,
    "overlap": overlap, "cat_sim": cat_sim,
    "other_posts": other_posts, "my_posts": my_posts,
    "scores": scores, "total": total,
})
import copywriter, render
copywriter.prepare()
render.run(scores, total)
