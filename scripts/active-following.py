#!/usr/bin/env python3
"""
活跃关注降级采集 —— 对方关注列表不可用时的替代方案。

官方 `friendships friends/other` 不存在（仅 friends/biz 可查自己），
因此用「对方微博中的转发来源 + @过的账号」作为对方"活跃关注"的近似样本。
对原创型博主（转发少/@少），补充「正文高频提及词」作为内容圈层信号。

用法:
    python3 active-following.py --uid <对方UID> [--count 100] [--my-uid <我方UID>] [--output json|table]

流程:
    1. 拉对方微博 user_timeline/other（max_id 分页，每页 20 条）
    2. 提取 retweeted_status.user（转发来源账号，含完整资料，零额外调用）
    3. 提取微博文本中的 @账号 → show_batch/other 批量查详情（每批 ≤50）
    4. 合并去重 → 活跃关注样本
    5. 品类归类（screen_name + description + domain + url 关键词；description 常被 other 接口裁剪，标注置信度）
    6. 正文高频提及词 → 内容圈层品类分布（原创型博主主信号）
    7. 圈子兼容对比（--my-uid）：
       a. UID 硬交集：我方关注列表 ∩ 对方活跃关注
       b. 品类相似度：我方关注列表品类分布 vs 对方活跃关注品类分布
       得分 = max(a, b)，标注降级方法

环境要求:
    - WEIBO_CLI_TOKEN 环境变量（weibo-cli 用）
    - 子进程调用 weibo-cli 必须继承 os.environ，不能用自定义 env 覆盖
"""
import json
import os
import re
import subprocess
import sys
import math
import datetime
from collections import Counter

# ---------- 品类分类（与 analysis-engine.md 模式三保持一致） ----------
CATEGORIES = {
    "军事": ["军事", "国防", "武器", "战略", "战机", "导弹", "军武"],
    "财经": ["股票", "基金", "投资", "理财", "A股", "牛市", "财经", "金融", "经济"],
    "时政": ["政策", "两会", "国际", "外交", "评论", "政务", "时政"],
    "科技": ["科技", "数码", "互联网", "AI", "产品", "编程", "开源", "芯片", "软件", "开发", "极客", "人工智能", "模型", "数据", "算法", "机器人", "智能", "代码", "云计算", "大模型", "agent", "算法"],
    "娱乐": ["明星", "综艺", "影视", "八卦", "追星", "娱乐", "电影", "音乐", "艺人"],
    "生活": ["美食", "旅行", "穿搭", "家居", "日常", "生活", "摄影", "萌宠", "做饭", "咖啡"],
    "媒体": ["日报", "晚报", "时报", "新闻", "媒体", "观察", "频道", "记者", "卫视", "电视台", "主编"],
    "知识": ["科普", "历史", "文化", "教育", "读书", "知识", "学者", "教授", "作家", "心理", "哲学"],
    "搞笑": ["搞笑", "段子", "沙雕", "幽默", "吐槽"],
    "情感": ["情感", "两性", "恋爱", "治愈", "星座", "婚姻"],
}

# 品牌/产品关键词 → 内容圈层品类（原创型博主正文信号）
BRAND_CATEGORY = {
    "科技": ["Qwen", "Kimi", "月之暗面", "DeepSeek", "Claude", "GPT", "Gemini", "智谱", "混元", "豆包", "LongCat", "Anthropic", "OpenAI", "Minimax", "fable", "EQBench", "GitHub", "开源", "PromptXRay", "VibeOps", "TRAE", "通义", "讯飞", "阶跃", "文心", "Llama", "Mistral", "Copilot", "Cursor"],
    "媒体": ["深圳卫视", "卫视", "电视台", "记者", "采访", "节目", "栏目", "播客"],
    "工作创作": ["自媒体", "选题", "热点", "舆情", "运营", "创作", "拍摄", "剪辑", "视频", "专栏"],
}

def categorize(account):
    """基于 screen_name + description + domain + url 归类账号品类，返回 (品类, 置信度, 信号源)"""
    signals = []
    text_parts = []
    for field in ["screen_name", "description", "remark"]:
        v = account.get(field)
        if v:
            text_parts.append(str(v))
            signals.append(field)
    for field in ["domain", "url"]:
        v = account.get(field)
        if v:
            text_parts.append(str(v))
            signals.append(field)
    text = " ".join(text_parts).lower()
    if not text.strip():
        return ("未知", 0.0, "无资料")
    hits = {}
    for cat, kws in CATEGORIES.items():
        n = sum(1 for kw in kws if kw.lower() in text)
        if n:
            hits[cat] = hits.get(cat, 0) + n
    if not hits:
        return ("未知", 0.0, "关键词未命中")
    best = max(hits, key=hits.get)
    # 置信度：description 存在且命中 → 高；仅 screen_name/domain 命中 → 中
    conf = min(hits[best] / 2.0, 1.0)
    if "description" not in signals:
        conf = min(conf, 0.5)
    return (best, conf, "+".join(signals))

# ---------- weibo-cli 调用 ----------
def cli(args):
    """调用 weibo-cli，继承 os.environ（Token 在 WEIBO_CLI_TOKEN 环境变量）"""
    env = dict(os.environ)
    env["NODE_OPTIONS"] = ""  # 避免继承可能冲突的 NODE_OPTIONS
    r = subprocess.run(["weibo-cli"] + args, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        err = r.stderr[-500:] if r.stderr else r.stdout[-500:]
        raise RuntimeError(f"weibo-cli {' '.join(args[:3])} failed: {err}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"weibo-cli non-JSON output: {r.stdout[-500:]}")

def fetch_timeline(uid, target=100):
    """拉取对方微博（max_id 分页，每页 20 条），返回微博列表"""
    all_posts, seen, max_id, page = [], set(), None, 0
    while len(all_posts) < target and page < 10:
        args = ["statuses", "user_timeline/other", "--uid", uid, "--count", "20", "--output", "json"]
        if max_id:
            args += ["--max_id", str(max_id)]
        d = cli(args)
        statuses = d.get("statuses") or []
        if not statuses:
            break
        for s in statuses:
            sid = s.get("id")
            if sid not in seen:
                seen.add(sid)
                all_posts.append(s)
        max_id = all_posts[-1]["id"]
        page += 1
    return all_posts

def extract_mentions(text):
    """提取微博文本中的 @账号（含转发链）"""
    if not text:
        return []
    return re.findall(r"@([\w\u4e00-\u9fa5\-\.]+)", text)

def content_circle(posts):
    """正文高频提及词 → 内容圈层品类分布（原创型博主主信号）"""
    text = " ".join(p.get("text", "") for p in posts)
    hits = Counter()
    for cat, brands in BRAND_CATEGORY.items():
        n = 0
        for b in brands:
            n += len(re.findall(re.escape(b), text, re.IGNORECASE))
        if n:
            hits[cat] = n
    total = sum(hits.values())
    if not total:
        return {}
    return {cat: round(n / total, 3) for cat, n in hits.most_common()}

# ---------- 主流程 ----------
def main():
    import argparse
    ap = argparse.ArgumentParser(description="活跃关注降级采集")
    ap.add_argument("--uid", required=True, help="目标用户 UID")
    ap.add_argument("--count", type=int, default=100, help="拉取微博条数（默认100）")
    ap.add_argument("--my-uid", default=None, help="我方 UID（提供时计算圈子兼容对比）")
    ap.add_argument("--output", default="json", choices=["json", "table"])
    args = ap.parse_args()

    print(f"== 拉取微博（{args.count}条）==", file=sys.stderr)
    posts = fetch_timeline(args.uid, args.count)
    print(f"  实得 {len(posts)} 条", file=sys.stderr)

    # 1. 转发来源账号（retweeted_status.user，含完整资料）
    repost_accounts = []
    for p in posts:
        rt = p.get("retweeted_status")
        if rt and rt.get("user"):
            repost_accounts.append(rt["user"])

    # 2. @过的账号（文本提取，需要批量查详情）
    mention_names = set()
    for p in posts:
        for name in extract_mentions(p.get("text", "")):
            mention_names.add(name)
    mention_accounts = []
    names = [n for n in mention_names if n not in {a.get("screen_name") for a in repost_accounts}]
    for i in range(0, len(names), 50):
        batch = names[i:i + 50]
        try:
            d = cli(["users", "show_batch/other", "--screen_name", ",".join(batch), "--output", "json"])
            mention_accounts.extend(d.get("users") or [])
        except RuntimeError as e:
            print(f"  ⚠️ @账号批量查询失败（{len(batch)}个）: {str(e)[:120]}", file=sys.stderr)

    # 3. 合并去重（按 uid，无 uid 按 screen_name），记录来源
    merged, seen_keys = [], set()
    repost_ids = {a.get("id") for a in repost_accounts}
    for acc in repost_accounts + mention_accounts:
        key = acc.get("id") or acc.get("screen_name")
        if key and key not in seen_keys:
            seen_keys.add(key)
            acc["_source"] = "repost" if acc.get("id") in repost_ids else "mention"
            merged.append(acc)

    # 4. 品类归类（description 常被 other 接口裁剪 → 置信度标注）
    cat_counter = Counter()
    accounts_detail = []
    for acc in merged:
        cat, conf, sig = categorize(acc)
        cat_counter[cat] += 1
        accounts_detail.append({
            "id": acc.get("id"),
            "screen_name": acc.get("screen_name"),
            "followers_count": acc.get("followers_count", 0),
            "verified": bool(acc.get("verified")),
            "category": cat,
            "confidence": conf,
            "signal": sig,
            "source": acc.get("_source"),
        })

    total = len(merged)
    cat_dist = {cat: round(cnt / total, 3) for cat, cnt in cat_counter.most_common()} if total else {}
    circle_dist = content_circle(posts)

    # 5. 成分标签（复用 analysis-engine.md 规则）
    labels = []
    if cat_dist:
        top2 = sum(v for _, v in list(cat_counter.most_common(2)))
        if cat_counter.get("军事", 0) + cat_counter.get("财经", 0) > total * 0.5:
            labels.append("战略家")
        if cat_counter.get("娱乐", 0) > total * 0.4:
            labels.append("饭圈居民")
        if cat_counter.get("科技", 0) > total * 0.3:
            labels.append("数字原住民")
        if cat_counter.get("生活", 0) + cat_counter.get("美食", 0) > total * 0.4:
            labels.append("生活家")
        if top2 > total * 0.7:
            labels.append("茧房居民")
        max_cat = cat_counter.most_common(1)[0][1] if cat_counter else 0
        if max_cat <= total * 0.25:
            labels.append("杂食动物")
        big_v = sum(1 for a in merged if a.get("followers_count", 0) > 1_000_000)
        if big_v > total * 0.6:
            labels.append("头部信徒")
    # 内容圈层补充标签
    if circle_dist:
        top1 = max(circle_dist.items(), key=lambda x: x[1]) if circle_dist else None
        if top1 and top1[1] > 0.6:
            labels.append(f"{top1[0]}重度圈层")

    result = {
        "uid": args.uid,
        "sample_size": total,
        "repost_accounts": len(repost_accounts),
        "mention_accounts": len(mention_accounts),
        "accounts": accounts_detail,
        "category_distribution": cat_dist,
        "content_circle": circle_dist,
        "labels": labels,
        "note": "降级数据：对方关注列表接口不可用，此样本为转发来源+@账号的活跃关注近似；content_circle 为正文提及词的内容圈层信号",
    }

    # 6. 圈子兼容对比（可选：提供 --my-uid 时）
    if args.my_uid:
        try:
            # 优先复用登录用户关注列表缓存（pair.py 翻页拉取的完整版），避免每次重跑重复烧调用
            cache_dir = os.environ.get("WEIBO_PAIR_CACHE", "/var/minis/workspace")
            # 关注列表缓存按登录用户命名（与 pair.py 口径一致；登录 UID 优先，my_uid 兜底）
            login_uid = None
            try:
                import json as _json
                ld = _json.load(open(f"{cache_dir}/pair_login_uid.json"))
                login_uid = ld.get("uid")
            except Exception:
                pass
            fcache = f"{cache_dir}/pair_my_following_{login_uid or args.my_uid}.json"
            my_following = None
            if os.path.exists(fcache):
                try:
                    my_following = json.load(open(fcache)).get("users")
                except Exception:
                    pass
            if not my_following:
                d = cli(["friendships", "friends/biz", "--count", "20", "--output", "json"])
                my_following = d.get("users") or []
                json.dump({"users": my_following, "fetched_at": str(datetime.datetime.now())},
                          open(fcache, "w"), ensure_ascii=False)
            my_ids = {u.get("id") for u in my_following}
            their_ids = {a.get("id") for a in merged if a.get("id")}
            inter = my_ids & their_ids
            overlap_rate = len(inter) / len(their_ids) if their_ids else 0
            # 我方关注列表品类分布
            my_cat = Counter()
            for u in my_following:
                c, _, _ = categorize(u)
                my_cat[c] += 1
            my_dist = {c: v / len(my_following) for c, v in my_cat.items()} if my_following else {}
            # 品类相似度：我方关注 vs 对方活跃关注（含未知占比）
            keys = set(my_dist) | set(cat_dist)
            dot = sum(my_dist.get(k, 0) * cat_dist.get(k, 0) for k in keys)
            n1 = math.sqrt(sum(v * v for v in my_dist.values()))
            n2 = math.sqrt(sum(v * v for v in cat_dist.values()))
            cat_sim = dot / (n1 * n2) if n1 and n2 else 0
            result["circle_compat"] = {
                "method": "降级（对方关注列表不可用）",
                "uid_overlap_rate": round(overlap_rate, 3),
                "uid_intersection": sorted(str(i) for i in inter),
                "my_following_count": len(my_following),
                "category_similarity": round(cat_sim, 3),
                "content_circle_overlap": round(cat_sim, 3),
                "score": round(max(overlap_rate, cat_sim), 3),
            }
        except RuntimeError as e:
            result["circle_compat"] = {"method": "降级", "error": str(e)[:200]}

    if args.output == "table":
        print(f"\n活跃关注样本: {total} 个（转发来源 {len(repost_accounts)} + @账号 {len(mention_accounts)}）")
        print(f"品类分布: {cat_dist}")
        print(f"内容圈层: {circle_dist}")
        print(f"成分标签: {labels}")
        print("\n样本明细（前12）:")
        for a in accounts_detail[:12]:
            print(f"  [{a['source']}] {a['screen_name']} | {a['category']}(conf={a['confidence']}) | 粉{a['followers_count']} | 信号:{a['signal']}")
        if "circle_compat" in result:
            cc = result["circle_compat"]
            print(f"\n圈子兼容({cc.get('method')}): UID交集率 {cc.get('uid_overlap_rate')} | 品类相似度 {cc.get('category_similarity')} | 得分 {cc.get('score')}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
