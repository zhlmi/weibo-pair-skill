#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微博配对 · 分析层：话题/品类/极性词表 + 七维面相 + 圈子兼容 + 缘分扫描。"""
import math, re
from collections import Counter

import config
import weibo_api
from lexicons import TOPICS, CATS, NEG, POS, NEG_FALSE, THIRD, YOU, TECH_KW

def full_text(p):
    t = p.get("text", "") or ""
    rt = p.get("retweeted_status")
    if rt:
        t += " " + (rt.get("text", "") or "")
        rt2 = rt.get("retweeted_status")
        if rt2: t += " " + (rt2.get("text", "") or "")
    return t


def seven_dimensions(posts, nickname):
    """七维面相分析：作息/话题/情绪/互动/创作/表达 + 基础统计"""
    hours = Counter(); times = []
    for p in posts:
        dt = weibo_api.parse_time(p.get("created_at", ""))
        if dt: hours[dt.hour] += 1; times.append(dt)
    total_t = len(times)
    night = sum(v for k, v in hours.items() if 22 <= k or k < 4) / max(total_t, 1)
    early = sum(v for k, v in hours.items() if 6 <= k <= 9) / max(total_t, 1)
    peak = [h for h, c in hours.most_common(3)]

    text = " ".join(full_text(p) for p in posts).lower()
    scores = Counter()
    for topic, kws in TOPICS.items():
        for kw in kws:
            scores[topic] += text.count(kw.lower())
    tot = sum(scores.values())
    dist = {k: round(v / tot, 3) for k, v in scores.most_common()} if tot else {}
    ent = -sum(p * math.log2(p) for p in dist.values() if p > 0) if dist else 0

    pos = sum(1 for p in posts if any(w in p.get("text", "") for w in ["开心","哈哈","太棒","棒","喜欢","爱","感谢","期待","恭喜","漂亮","爽","好","牛","厉害","不错","支持","加油","努力"]))
    neg = sum(1 for p in posts if any(w in p.get("text", "") for w in ["难过","烦","讨厌","累","崩溃","无语","失望","焦虑","痛","哭","气","糟","差","失败","问题","bug","错误"]))

    reposts = sum(1 for p in posts if p.get("repost") or p.get("retweeted_status"))
    orig = 1 - reposts / max(len(posts), 1)
    ex = el = qu = 0
    lens = []
    for p in posts:
        t = p.get("text", "") or ""
        ex += t.count("!") + t.count("！"); el += t.count("...") + t.count("……"); qu += t.count("?") + t.count("？")
        lens.append(len(t))
    n = len(posts)
    span = (max(times) - min(times)).days if len(times) > 1 else 0
    return {
        "nickname": nickname,
        "作息": {"peak": sorted(peak), "night": round(night, 2), "early": round(early, 2), "daily": round(n / max(span, 1), 2), "span": span, "hours": dict(hours)},
        "话题": {"top": [k for k, _ in scores.most_common(3)], "dist": dist, "diversity": round(ent / math.log2(len(dist)), 2) if len(dist) > 1 else 0},
        "情绪": {"avg": round((pos - neg) / n, 3), "mood": "正面" if pos > neg else ("负面" if neg > pos else "中性"), "pos": pos, "neg": neg},
        "互动": {"style": "原创型" if orig > 0.7 else ("搬运型" if orig < 0.3 else "混合型"), "orig": round(orig, 2)},
        "创作": {"orig": round(orig, 2), "avg_len": round(sum(lens) / n, 1)},
        "表达": {"ex": round(ex / n, 2), "el": round(el / n, 2), "qu": round(qu / n, 2)},
    }


def cos(a, b):
    ks = set(a) | set(b)
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in ks)
    na = math.sqrt(sum(v * v for v in a.values())); nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0


def categorize(acc):
    """账号品类归类（圈子兼容降级用）"""
    parts = " ".join(str(acc.get(f, "")) for f in ["screen_name", "description", "remark", "domain", "url"]).lower()
    if not parts.strip(): return "未知"
    hits = Counter()
    for cat, kws in CATS.items():
        hits[cat] = sum(1 for kw in kws if kw.lower() in parts)
    if not hits: return "未知"
    return hits.most_common(1)[0][0]


def sleep_score(ha_, hb_):
    """作息同步（峰值重合率）：双方 top3 活跃高峰，误差 ≤1h 全重合（1.0）、1-2h 半重合（0.5）、>2h 不重合（0）。
    匹配度 = 我方峰值重合分 / 3，语义：'我的活跃高峰，TA 在不在场'。"""
    def peaks(c):
        return [h for h, _ in sorted(((h, c.get(h, 0)) for h in range(24) if c.get(h, 0)), key=lambda t: -t[1])[:3]]
    pa, pb = peaks(ha_), peaks(hb_)
    if not pa or not pb: return 0.0, 0
    def align(x):
        d = min(abs(x - y) for y in pb)
        if d <= 1: return 1.0
        if d <= 2: return 0.5
        return 0.0
    hits = sum(align(x) for x in pa)
    return round(hits / 3, 3), hits


def density_to_fate(d):
    """互动密度 → 缘分分数（v1.7.0 密度归一：每百条加权互动次数，跨样本量可比）。
    校准：d=0→0；0.3→0.18；1.2→0.50；5→0.95 封顶。"""
    if d <= 0: return 0.0
    if d >= 5: return 0.95
    if d >= 1.2: return 0.5 + 0.45 * (d - 1.2) / 3.8
    if d >= 0.3: return 0.18 + 0.32 * (d - 0.3) / 0.9
    return 0.18 * (d / 0.3)


def scan_fate(my_posts, other_posts, my_uid, my_nick, other_uid, other_nick):
    """从已缓存微博零成本扫描双向互动信号：
      - 直接转发（retweeted_status.user.id == 对方）  0.45/次
      - 回复（in_reply_to_user_id == 对方）           0.35/次
      - 独立 @提及（非转发链格式）                     0.20/次
      - 转发链共现（//@对方 在传播链）                 0.10/条（技术内容 0.15，v1.7.0 加权）
      - 互关（我方关注列表含对方）                     0.10
    v1.7.0 密度归一：缘分 = density_to_fate(加权互动 / min(双方样本) × 100)。
    """
    signals = {"direct_repost": 0, "reply": 0, "at": 0, "chain": 0, "chain_tech": 0, "follow": 0}
    details = []
    interactions = []
    def scan(posts, target_uid, target_nick, direction):
        victim = "我方" if direction == "对方" else "对方"  # 被转发/被回复/被提及方 = 扫描方对侧
        for p in posts:
            text = p.get("text", "") or ""
            rt = p.get("retweeted_status") or {}
            ru = rt.get("user") or {}
            if str(ru.get("id")) == str(target_uid):
                signals["direct_repost"] += 1
                details.append(f"{direction}转发{victim}原创：{text[:40]}")
                interactions.append(text)
            if str(p.get("in_reply_to_user_id", "")) == str(target_uid):
                signals["reply"] += 1
                details.append(f"{direction}回复{victim}：{text[:40]}")
                interactions.append(text)
            chain = set(re.findall(r"//@([\w\u4e00-\u9fa5\-\.]+)", text))
            if target_nick in chain:
                if TECH_KW.search(text):
                    signals["chain_tech"] += 1  # 技术内容共现加权（×1.5）
                    details.append(f"{direction}转发链共现（技术内容）：{text[:40]}")
                else:
                    signals["chain"] += 1  # 按微博计，天然去重
                    details.append(f"{direction}转发链共现（同一条传播链）：{text[:40]}")
                interactions.append(text)
            elif target_nick in set(re.findall(r"@([\w\u4e00-\u9fa5\-\.]+)", text)):
                signals["at"] += 1
                details.append(f"{direction}@提及{victim}：{text[:40]}")
                interactions.append(text)
    scan(my_posts, other_uid, other_nick, "我方")
    scan(other_posts, my_uid, my_nick, "对方")

    # 互关：尽力翻页查找对方是否在我方关注列表（count 上限 20 → 最多翻 10 页=200 人，
    # 找不到不代表没互关，用户确认用 --mutual-follow 兜底；报告会标注检测覆盖范围）
    def find_in_following(target_uid):
        users, src = weibo_api.load_following()
        if not users:
            return None  # 限流/无缓存，标记未知
        return str(target_uid) in {str(u.get("id")) for u in users}

    if config.MUTUAL_FOLLOW:
        signals["follow"] = 1
        details.append("互关：用户确认双方互关")
    elif not config.IS_SELF:
        follow_state = "n/a"  # A×B：friends/biz 只能查登录用户，A×B 互关自动检测不可行
        details.append("互关：A×B 配对自动检测不可行（API 仅登录用户），可用 --mutual-follow 由用户确认")
    else:
        follow_state = find_in_following(str(other_uid))
        if follow_state is True:
            signals["follow"] = 1
            details.append("互关：对方在你的关注列表中")
        elif follow_state is False:
            pass  # 明确不在 → 不互关，0 分
        else:
            pass  # 翻页未覆盖或限流 → 按 0 计，不冤枉（报告标注）

    raw = (signals["direct_repost"] * 0.45 + signals["reply"] * 0.35 +
           signals["at"] * 0.20 + signals["chain_tech"] * 0.15 + signals["chain"] * 0.10 + signals["follow"] * 0.10)
    # v1.7.0 密度归一：每百条加权互动次数（分母取双方样本较小者作共同观察窗口）
    _min_n = min(len(my_posts), len(other_posts)) or 1
    density = round(raw / _min_n * 100, 2)
    follow_state = ("confirmed" if config.MUTUAL_FOLLOW else ("found" if signals["follow"]
                    else ("n/a" if not config.IS_SELF else "uncovered")))

    # 互动极性（数量 × 质量）：负面词做指向性分析：指向对方才算关系摩擦；
    # 指向第三方（工作/项目/体制等）是吐槽日常；NEG_FALSE 排除正则误报。
    pos = neg = third_neg = 0
    for t in interactions:
        pos += len(POS.findall(t))
        n = len(NEG.findall(t))
        if n:
            if THIRD.search(t) and not YOU.search(t):
                third_neg += n
            else:
                neg += n
    total_p = pos + neg
    polarity = "positive"
    if total_p:
        neg_share = neg / total_p
        if neg_share >= 0.5: polarity = "negative"
        elif neg_share >= 0.3: polarity = "mixed"
    fate = round(density_to_fate(density), 3)
    if config.POLARITY_NOTE:
        polarity = "positive"   # 用户确认的关系事实优先，跳过极性打折
    elif polarity == "negative":
        fate = round(fate * 0.3, 3)
    elif polarity == "mixed":
        fate = round(fate * 0.6, 3)
    return fate, signals, details, follow_state, polarity, pos, neg, third_neg, density
