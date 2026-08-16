#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博自画像 · 数字面相（相面术）
你的微博就是你的面相。

用法:
    python3 self-portrait.py                        # 本人, weibo-skill 免费 100 条
    python3 self-portrait.py --count 500            # 本人, CLI 500 条
    python3 self-portrait.py --output 面相.html     # 自定义输出路径
    python3 self-portrait.py --nick 昵称            # 覆盖昵称

依赖: weibo-skill（≤100 条免费）或 weibo-cli（>100 条, 需 WEIBO_CLI_TOKEN）
输出: 面相诊断书 HTML（templates/portrait.html 渲染）
"""
import argparse, json, os, re, sys, math, subprocess, datetime, random
from collections import Counter

from lexicons import TOPICS
import weibo_api

_ap = argparse.ArgumentParser(description="微博自画像 · 数字面相")
_ap.add_argument("--count", type=int, default=100, help="采样条数（默认100走weibo-skill免费；>100走weibo-cli）")
_ap.add_argument("--output", default=None, help="HTML 输出路径（缺省：<缓存目录>/self-portrait.html）")
_ap.add_argument("--cache-dir", default=os.environ.get("WEIBO_PAIR_CACHE", "/var/minis/workspace"), help="缓存目录（缺省：$WEIBO_PAIR_CACHE 或 /var/minis/workspace）")
_ap.add_argument("--nick", default=None, help="昵称（缺省自动获取）")
_ap.add_argument("--template", choices=["portrait","mingpan"], default="portrait", help="输出模板：portrait=面相诊断书（默认）/ mingpan=星空罗盘动效版")
_ap.add_argument("--on-short", choices=["ask","continue","abort"], default="ask",
                 help="数据不足目标量时的策略：ask=询问用户（默认；非交互退出码3）/ continue=用现有数据继续 / abort=中止（退出码2）")
_a = _ap.parse_args()

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS_DIR = os.path.join(os.path.dirname(SKILL_DIR), "weibo-skill", "scripts", "weibo-skill.js")
CACHE_DIR = _a.cache_dir
TEMPLATE = os.path.join(SKILL_DIR, "templates", "portrait.html")
MINGPAN_TPL = os.path.join(SKILL_DIR, "templates", "mingpan.html")
if not _a.output:
    _a.output = f"{CACHE_DIR}/self-portrait.html"
TEMPLATE_NAME = _a.template
ON_SHORT = _a.on_short

def cli(args):
    env = dict(os.environ); env["NODE_OPTIONS"] = ""
    r = subprocess.run(["weibo-cli"] + args, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"weibo-cli failed: {r.stderr[-300:]}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"non-JSON: {r.stdout[-300:]}")

parse_time = weibo_api.parse_time

def get_login_uid():
    """当前登录用户 UID（weibo-skill/CLI biz 只能操作登录用户本人）"""
    cache = f"{CACHE_DIR}/pair_login_uid.json"
    if os.path.exists(cache):
        try:
            d = json.load(open(cache))
            if d.get("uid"): return d["uid"]
        except Exception:
            pass
    try:
        d = cli(["users", "show/biz", "--output", "json"])
        uid = None
        for u in (d.get("users") or [d]):
            if u.get("id"): uid = str(u["id"]); break
        if uid:
            json.dump({"uid": uid, "fetched_at": str(datetime.datetime.now())}, open(cache, "w"))
        return uid
    except Exception as e:
        print(f"  ⚠️ 登录用户检测失败: {str(e)[:80]}", file=sys.stderr)
        return None

# ---------- 1. 采集 ----------
fetch_timeline = weibo_api.fetch_timeline

LOGIN_UID = get_login_uid()
MY_CACHE = f"{CACHE_DIR}/pair_my_posts_{LOGIN_UID or 'self'}.json"

def confirm_short(label, got, want):
    """数据不足目标量时的策略：ask（默认，交互询问；非交互环境退出码 3）/ continue / abort（退出码 2）。
    只在本次新抓取后调用（缓存命中视为用户已接受现状，不询问）。"""
    if got >= want * 0.9:
        return
    if ON_SHORT == "continue":
        print(f"  ⚠️ [{label}] 数据不足（{got}/{want}），按 --on-short continue 用现有数据继续", file=sys.stderr)
        return
    if ON_SHORT == "abort":
        print(f"  ⛔ [{label}] 数据不足（{got}/{want}），按 --on-short abort 中止。缓存已落盘，重跑自动断点续传。", file=sys.stderr)
        sys.exit(2)
    print(f"\n  ⚠️ [{label}] 数据不完整：{got}/{want} 条（限流中断或微博量本身不足）", file=sys.stderr)
    print("     已自动落盘缓存，重跑会断点续传。请选择：", file=sys.stderr)
    print("     1) 用当前数据继续生成报告（--on-short continue）", file=sys.stderr)
    print("     2) 中止，稍后重跑自动续传补齐（--on-short abort）", file=sys.stderr)
    if sys.stdin.isatty():
        try:
            choice = input("     输入 1 或 2：").strip()
        except EOFError:
            choice = ""
        if choice == "1":
            print("  ✔ 继续", file=sys.stderr)
            return
        print("  ⛔ 已中止。", file=sys.stderr)
        sys.exit(2)
    print("  [非交互环境] 未指定策略，退出等待决策。可用 --on-short continue / --on-short abort 指定。", file=sys.stderr)
    sys.exit(3)

def load_cache(path, need):
    if os.path.exists(path):
        try:
            d = json.load(open(path))
            if len(d) >= int(need * 0.9):
                return d
        except Exception:
            pass
    return None

print("== 采集微博 ==", file=sys.stderr)
posts = load_cache(MY_CACHE, _a.count)
if posts is not None:
    print(f"{len(posts)} 条（命中缓存，跳过 API）", file=sys.stderr)
elif _a.count <= 100:
    try:
        r = subprocess.run(["node", WS_DIR, "status", "--count=100"], capture_output=True, text=True)
        my_raw = json.loads(r.stdout)
    except Exception as e:
        print(f"  ⚠️ weibo-skill 调用失败: {e}", file=sys.stderr)
        my_raw = {}
    snap = my_raw.get("data", {}).get("statuses", [])
    cached_posts = load_cache(MY_CACHE, 1) or []
    if cached_posts:
        _seen = {p.get("id") for p in cached_posts if p.get("id")}
        _added = 0
        for p in snap:
            if p.get("id") not in _seen:
                cached_posts.append(p); _added += 1
        print(f"  ℹ️ 已有部分缓存 {len(snap)}→merge 后 {len(cached_posts)} 条（新增 {_added}）", file=sys.stderr)
        posts = cached_posts
    else:
        posts = snap
    json.dump(posts, open(MY_CACHE, "w"), ensure_ascii=False)
else:
    cached = load_cache(MY_CACHE, 1)  # 部分缓存 → 断点续传
    if cached:
        print(f"  断点续传：已有 {len(cached)} 条缓存，继续拉取", file=sys.stderr)
    posts = fetch_timeline(LOGIN_UID, _a.count, resume_from=cached)
    json.dump(posts, open(MY_CACHE, "w"), ensure_ascii=False)
    confirm_short("微博", len(posts), _a.count)
if not posts:
    raise RuntimeError("微博采集为空：请检查 weibo-skill 登录（≤100）或 CLI 服务与 Token（>100）")
print(f"{len(posts)} 条", file=sys.stderr)
# 高精度随机种子：iSH 环境 os.urandom 采样可能秒级重复，纳秒+pid 保证每次输出文案不同
random.seed(int(datetime.datetime.now().timestamp() * 1_000_000) ^ os.getpid())

# ---------- 2. 七维分析 ----------
TOPICS = TOPICS  # 来自 lexicons

def full_text(p):
    t = p.get("text","") or ""
    rt = p.get("retweeted_status")
    if rt:
        t += " " + (rt.get("text","") or "")
        rt2 = rt.get("retweeted_status")
        if rt2: t += " " + (rt2.get("text","") or "")
    return t

def analyze(posts):
    hours = Counter(); times = []
    for p in posts:
        dt = parse_time(p.get("created_at",""))
        if dt: hours[dt.hour] += 1; times.append(dt)
    n = len(times)
    night = sum(v for k,v in hours.items() if 22 <= k or k < 4) / max(n,1)
    early = sum(v for k,v in hours.items() if 6 <= k <= 9) / max(n,1)
    noon  = sum(v for k,v in hours.items() if 11 <= k <= 14) / max(n,1)
    peak = [h for h,c in hours.most_common(3)]
    text = " ".join(full_text(p) for p in posts).lower()
    scores = Counter()
    for topic, kws in TOPICS.items():
        for kw in kws:
            scores[topic] += text.count(kw.lower())
    tot = sum(scores.values())
    dist = {k: round(v/tot,3) for k,v in scores.most_common()} if tot else {}
    ent = -sum(p*math.log2(p) for p in dist.values() if p>0) if dist else 0
    pos = sum(1 for p in posts if any(w in p.get("text","") for w in ["开心","哈哈","太棒","棒","喜欢","爱","感谢","期待","恭喜","漂亮","爽","好","牛","厉害","不错","支持","加油","努力"]))
    neg = sum(1 for p in posts if any(w in p.get("text","") for w in ["难过","烦","讨厌","累","崩溃","无语","失望","焦虑","痛","哭","气","糟","差","失败","问题","bug","错误"]))
    reposts = sum(1 for p in posts if p.get("repost") or p.get("retweeted_status"))
    orig = 1 - reposts/max(n,1)
    ex = el = qu = 0; lens = []
    for p in posts:
        t = p.get("text","") or ""
        ex += t.count("!")+t.count("！"); el += t.count("...")+t.count("……"); qu += t.count("?")+t.count("？")
        lens.append(len(t))
    span = (max(times)-min(times)).days if len(times)>1 else 0
    return {
        "n": n, "span": span, "daily": round(n/max(span,1), 2),
        "hours": dict(hours), "peak": sorted(peak), "night": round(night,2), "early": round(early,2), "noon": round(noon,2),
        "dist": dist, "top": [k for k,_ in scores.most_common(3)], "diversity": round(ent/math.log2(len(dist)),2) if len(dist)>1 else 0,
        "pos": pos, "neg": neg, "avg": round((pos-neg)/n,3),
        "orig": round(orig,2), "avg_len": round(sum(lens)/n,1),
        "ex": round(ex/n,2), "el": round(el/n,2), "qu": round(qu/n,2),
    }

A = analyze(posts)
print(json.dumps(A, ensure_ascii=False, indent=1), file=sys.stderr)

# ---------- 3. 面相映射 + 判词 ----------
def xiang_map(A):
    h = A["hours"]; n = A["n"]
    if A["night"] > 0.40: e = "子时额"
    elif A["early"] > 0.30: e = "卯时额"
    elif A["noon"] > 0.30: e = "午时额"
    else: e = "散时额"
    if A["orig"] < 0.40: y = "搬运眼"
    elif A["dist"].get("科技AI",0) > 0.30: y = "科技眼"
    elif A["dist"].get("美食",0) > 0.25: y = "美食眼"
    elif (max(A["dist"].values()) if A["dist"] else 0) < 0.20: y = "散光眼"
    else: y = "科技眼"
    if A["pos"] > A["neg"] and A["pos"]/max(n,1) > 0.60: q = "红润气"
    elif A["neg"]/max(n,1) > 0.40: q = "青白气"
    elif A["pos"] and A["neg"] and min(A["pos"],A["neg"])/max(A["pos"],A["neg"]) > 0.6: q = "彩虹气"
    else: q = "平和气"
    if A["daily"] > 3: k = "话唠口"
    elif A["orig"] > 0.70: k = "原创口"
    else: k = "闭口相"
    if A["daily"] > 3: g = "显骨"
    elif A["daily"] < 0.5: g = "隐骨"
    else: g = "常骨"
    if A["orig"] > 0.70: s = "创作手"
    elif A["orig"] < 0.30: s = "搬运手"
    else: s = "混合手"
    if A["ex"] >= 0.05: m = "叹眉"
    elif A["el"] >= 0.05: m = "省眉"
    elif A["qu"] >= 0.05: m = "问眉"
    else: m = "平眉"
    return {"额相": e, "眼相": y, "气色": q, "口相": k, "骨相": g, "手相": s, "眉相": m}

JUDGE = {
    "额相": {"散时额": ["思维自由，不受时间束缚。时辰无主，随时可醒", "时辰无主，灵感随时敲门。你的一天不是时间表，是心情板", "发帖不分昼夜，思维不受钟点管。散时型人格，自由是本能"],
             "子时额": ["主思维跳跃，灵感多于执行。凌晨三点常有顿悟", "深夜是你的主场，白天的灵感都欠着觉", "凌晨才是你的清醒时刻。与月亮的时差，是你和世界的时差"],
             "卯时额": ["自律极强，日程精确到分钟。朋友圈里最早的鸟", "早起打卡型人格。闹钟没响你已经醒了，朋友圈最早的鸟", "天光即灵感的开关，你的输出从清晨开始算"],
             "午时额": ["午休时间是创作高峰期。上班摸鱼的灵魂诗人", "午休是你的创作窗口。别人的午觉，你的灵感喷泉", "日头最高的时刻，你文思最旺"]},
    "眼相": {"科技眼": ["对新事物有天然嗅觉。发布会如过年，参数背得比课文熟", "参数是你的母语，发布会是你的春节", "对新产品有天生的雷达。别人看热闹，你看门道"],
             "美食眼": ["注意力长期锁定食物。朋友圈堪比大众点评", "味觉优先的注意力分配。食物在你眼里自带高光", "你的手机相册，半壁江山是吃的"],
             "散光眼": ["注意力均匀分布。什么都看，什么都不深", "什么都看什么都不深。信息时代的杂食动物", "注意力像散光，处处模糊又处处有光"],
             "搬运眼": ["信息整合能力强。不生产内容，只是内容的搬运工", "好内容先转再说。你是信息的中转站，不是终点", "不生产内容，但你是最好的筛子"]},
    "气色": {"红润气": ["心态积极，能量充沛。朋友圈里的小太阳", "正能量续航拉满。你的微博是充电站", "情绪面红润有光泽，谁看你都像看到晴天"],
             "青白气": ["近期情绪波动，内心戏丰富。深夜微博是情绪的出口", "情绪写在深夜。你的微博是情绪的地窖", "内心的戏比深夜的微博更长"],
             "平和气": ["情绪稳定，不喜不悲。别人吵架你在旁边喝茶", "情绪恒温。别人的火山喷发，你的温度计纹丝不动", "不喜不悲，稳如老狗，情绪管理大师"],
             "彩虹气": ["情绪丰富，一天能经历四季。这是艺术家的气质", "情绪二十四节气，一天能过完四季", "上午晴下午雨，你的人生永远有天气预报"]},
    "口相": {"话唠口": ["表达欲旺盛，存在感极强。微博就是你的直播间", "表达欲如黄河泛滥。微博就是你的直播间", "一天不说够字数，浑身难受。语言是你的呼吸"],
             "原创口": ["创造力强，有话要说。不转发别人的，只说自己想说的", "不借别人的嘴说话。你的微博全是自己人", "每一句都是原创，拒绝二手表达"],
             "互动口": ["社交能力强，喜欢和人交流。每条评论都认真回复", "社交电池永远满格。评论区是你的客厅", "每条评论都接得住。你是微博的迎宾员"],
             "闭口相": ["内心戏丰富但嘴上不说。点赞是你的表达方式", "内心弹幕横飞，嘴上云淡风轻", "点赞千言万语，评论惜字如金"]},
    "骨相": {"显骨": ["存在感强，刷屏能力一流。微博就是你的日记本", "存在感强到刷屏。你的微博是日记，也是广播", "人群里的显性基因。想忽略你都难"],
             "隐骨": ["存在感低但质量高。朋友圈里的扫地僧", "潜水大师。偶尔冒泡，泡泡必是精品", "不鸣则已，一鸣惊人。微博界的扫地僧"],
             "常骨": ["存在感适中，频率健康。不刷屏也不消失", "频率稳定，存在感恰到好处。不刷屏也不隐身", "稳字当头。你的微博节奏像钟摆"]},
    "手相": {"创作手": ["原创能力强，有表达欲。每条微博都是自己的想法", "字字原创，句句自己人。你是内容的生产者", "你的微博是草稿箱，也是作品集"],
             "搬运手": ["信息嗅觉灵敏，是朋友圈的编辑。好内容先转再说", "信息编辑部的资深编辑。转发的都是精品", "搬运不是复制，是筛选。你是最好的荐书人"],
             "混合手": ["既能创作也能整合。自己写和转别人的五五开", "原创和转发五五开。既能写也能淘", "自己写一段，再转一段。你的微博是自选集"]},
    "眉相": {"叹眉": ["情绪外放，表达欲强。每个感叹号都是内心的放大器", "情绪外放型。感叹号是你的音量键", "每句话都自带叹号。你的情绪不需要翻译"],
             "省眉": ["留白型人格，暗示多于明说。话不说完，意思自己品", "话只说一半，剩下自己品。留白是你的风格", "省略号是你的标点，暗示是你的语言"],
             "问眉": ["好奇心强，喜欢提问。评论区就是你的知乎", "问题比答案多。你的微博是十万个为什么", "好奇心永动机。你的评论区就是知乎"],
             "平眉": ["冷静理性，情绪内敛。文字像手术刀一样精准", "冷静理性，标点都克制。文字像手术刀", "不带情绪的发帖者。你的微博像说明书"]},
}
KEY = {"散时额":"自由","子时额":"夜思","卯时额":"自律","午时额":"午慧","科技眼":"敏锐","美食眼":"食趣","散光眼":"广纳","搬运眼":"集讯","红润气":"明朗","青白气":"深郁","平和气":"定力","彩虹气":"丰沛","话唠口":"在场","原创口":"自述","互动口":"往来","闭口相":"内省","显骨":"在场","隐骨":"沉潜","常骨":"均衡","创作手":"原创","搬运手":"整合","混合手":"均衡","叹眉":"外放","省眉":"留白","问眉":"追问","平眉":"冷静"}
FLAG = {"话唠口":"高活跃","显骨":"高活跃","问眉":"追问型","科技眼":"科技向","隐骨":"潜水型","叹眉":"外放型","红润气":"阳光型","青白气":"深夜型","散光眼":"杂食型","搬运眼":"集讯型"}
SUB_NAME = {"额相":"思维","眼相":"焦点","气色":"情绪","口相":"表达","骨相":"存在","手相":"创作","眉相":"提问"}

XIANG = xiang_map(A)
X = XIANG

# 检查表行
def bar_pct(v): return max(4, min(96, int(v*100)))
rows = []

def pick(pool):
    """随机取文案候选（变体池，保证每次输出不重样）"""
    return random.choice(pool)
def add_row(item, term, bar, val_txt, flag=None):
    f = f'<span class="flag">{flag}</span>' if flag else ""
    rows.append(f'''<tr><td class="item-name">{item} <span style="font-size:10px;color:var(--ink-3)">{SUB_NAME[item]}</span></td><td class="item-type">{term}</td><td><span class="bar"><i style="width:{bar}%"></i></span> <span class="item-val">{val_txt}</span></td><td class="judge">{pick(JUDGE[item][term])}{f}</td></tr>''')

top_topic = A["top"][0] if A["top"] else "—"
top_pct = A["dist"].get(top_topic, 0)
add_row("额相", X["额相"], bar_pct(max(A["noon"], A["night"], A["early"])), f"午时{int(A['noon']*100)}% · 深夜{int(A['night']*100)}%")
add_row("眼相", X["眼相"], bar_pct(top_pct), f"{top_topic} {top_pct*100:.1f}%", FLAG.get(X["眼相"]))
add_row("气色", X["气色"], bar_pct(max(A["pos"], A["neg"])/max(A["n"],1)), f"正{A['pos']} · 负{A['neg']}")
add_row("口相", X["口相"], bar_pct(min(A["daily"]/15,1)), f"{A['daily']} 条/日", FLAG.get(X["口相"]))
add_row("骨相", X["骨相"], bar_pct(min(A["daily"]/15,1)), f"{A['daily']} 条/日")
add_row("手相", X["手相"], bar_pct(A["orig"]), f"原创率 {A['orig']*100:.0f}%")
add_row("眉相", X["眉相"], bar_pct(max(A["ex"], A["el"], A["qu"])*10), f"问号率 {A['qu']*100:.1f}% · 叹号率 {A['ex']*100:.1f}%", FLAG.get(X["眉相"]))

# 主诊断 + 综合判语
main3 = [X["额相"], X["眼相"], X["气色"]]
sub3 = [X["口相"], X["骨相"]]
concl1 = f"受检者呈 <span class=\"zh\">{' · '.join(main3)}</span>"
concl2 = f"兼 <span class=\"zh\">{' · '.join(sub3)}</span>，手相{X['手相']}，眉相{X['眉相']}"
keys = []
for t in [X["额相"], X["眼相"], X["气色"], X["口相"], X["骨相"], X["手相"], X["眉相"]]:
    k = KEY.get(t, "")
    if k and k not in keys: keys.append(k)
if A["daily"] >= 10: img = pick(["随时在线、永在输出的圈内广播站", "一个人就是一支刷屏军团的日更选手", "把微博当直播间的全天候播报员"])
elif A["daily"] >= 3: img = pick(["稳定在线、持续发声的常驻嘉宾", "有固定节目表的内容主播", "雷打不动的日更派"])
elif A["orig"] >= 0.7: img = pick(["低频高质的深度内容人", "少而精的原创型选手", "贵精不贵多的内容匠人"])
else: img = pick(["潜水但眼光毒辣的信息猎手", "低调潜伏、出手即精品的观察者", "安静但从不缺席的看客"])
_s_kk = '、'.join(f'{t}主{k}' for t, k in zip([X['额相'], X['眼相'], X['气色']], keys[:3]))
_s_inx = f"{X['口相']}、{X['骨相']}主{KEY.get(X['口相'], '在场')}"
_s_k1, _s_k2, _s_k3 = (KEY.get(X['额相'], ''), KEY.get(X['眼相'], ''), KEY.get(X['气色'], ''))
_s_data = (f"{A['daily']} 条/日的输出节奏，{top_topic} {top_pct*100:.0f}% 的话题浓度，"
           f"{'问号' if X['眉相']=='问眉' else '风格'}里藏着{'追问欲' if X['眉相']=='问眉' else '表达欲'}")
summary = pick([
    f"综合判语：{_s_kk}，{_s_inx}。合而观之：一位{img}。{_s_data}。",
    f"综合判语：七相之中，{X['额相']}掌{_s_k1}、{X['眼相']}掌{_s_k2}、{X['气色']}掌{_s_k3}；最显眼的是{_s_inx}的在场感。整体观之：{img}。{_s_data}。",
    f"综合判语：你的数字面相由{X['额相']}{X['眼相']}{X['气色']}定调：{_s_k1}是底色，{_s_k2}是锋芒，{_s_k3}是护城河。{img}。{_s_data}。",
])

# 医嘱（运势建议，荒诞但有洞察）
_q_pool = {
    "问眉": ["问号是你的触角，不是你的病", "问题是你丈量世界的方式，别停", "好奇心这么旺，值得被好好喂养"],
    "叹眉": ["感叹号是你的扬声器，不是你的喇叭", "情绪外放是天赋，别收着", "感叹号不要钱，但感情是限量款"],
    "省眉": ["省略号是你的留白，偶尔把话说完整试试", "话不说满，是温柔也是距离", "留白很美，但有些话值得说出口"],
    "平眉": ["句号是你的冷静，偶尔也激动一下", "理性是铠甲，偶尔露个缝", "你的冷静很值钱，但热情也不便宜"],
}
q_bits = pick(_q_pool.get(X["眉相"], _q_pool["平眉"]))
if A["daily"] >= 10: f_bits = pick(["话唠是天赐，但记得留一页给自己", "表达欲充沛是天分，偶尔留给沉默一次", "你在说话这件事上从不亏本，记得攒点留白"])
elif A["daily"] < 0.5: f_bits = pick(["潜水是修行，但大家想你了，多发点", "沉默是你的常态，偶尔冒个泡就是节日", "你不说话的时候，世界安静得让人不习惯"])
else: f_bits = pick(["这个节奏刚刚好，别改", "你的频率稳得像心跳，继续保持", "不多不少，恰到好处，这就是你的节奏感"])
if A["night"] > 0.4: t_bits = pick(["灵感银行开在深夜：白天攒，凌晨发，夜猫子们等你投喂", "你是夜的合伙人，灵感都走你的账", "凌晨的清醒是你的时区，别硬调"])
elif A["early"] > 0.3: t_bits = pick(["早起是你的结界：趁世界没醒，把话说给自己听", "清晨的灵感最干净，你懂的", "你是早晨的信使，第一缕光归你"])
else: t_bits = pick(["灵感银行开在傍晚：白天攒，黄昏发，关注你的人的下班路上有你", "黄昏是你的发稿黄金档，别人下班你上岗", "你的灵感走日间线，错峰出更有声量"])
if A["orig"] >= 0.7: o_bits = pick(["原创是天赋，别让转发稀释它", "你的脑子里有矿，别只挖不晒", "每一句原创都是你的签名，别签得太少"])
elif A["orig"] < 0.3: o_bits = pick(["偶尔写一句自己的话，让搬运变成推荐", "转发的尽头是原创，试试写第一句", "你的品味已经够好，该轮到自己产出了"])
else: o_bits = pick(["能写能转是本事，平衡就是你的风格", "原创和搬运两手抓，稳", "一半自己写一半帮人传，这个比例刚刚好"])
rx = f"{t_bits}。{f_bits}。{q_bits}。{o_bits}。"
rx_line = f"每日输出 {A['daily']} 条节奏不变 · 留白 1 页 · {('追问' if X['眉相']=='问眉' else '表达')}不设限"

# 生命体征
def fmt_emotion(avg):
    if avg >= 0.15: return "+" + f"{avg:.2f}", "偏正面"
    if avg <= -0.15: return f"{avg:.2f}", "偏负面"
    return f"{avg:+.2f}", "平稳"

emotion, emotion_note = fmt_emotion(A["avg"])
peaks = "·".join(str(h) for h in A["peak"])

# ---------- 4. 渲染 ----------
nick = _a.nick
if not nick:
    try:
        d = cli(["users", "show_batch/other", "--uids", str(LOGIN_UID), "--output", "json"])
        for u in (d.get("users") or []):
            if str(u.get("id")) == str(LOGIN_UID):
                nick = u.get("screen_name"); break
    except Exception:
        pass
nick = nick or f"用户{LOGIN_UID}"
today = datetime.date.today()

if TEMPLATE_NAME == "mingpan":
    # ---- 星盘版数据 ----
    def _term_html(t):
        return f'<b>{t[:-1]}</b>{t[-1]}'
    def _hl(k):
        return f'<span class="hl">{k}</span>'
    top_topic = A["top"][0] if A["top"] else "—"
    top_pct = A["dist"].get(top_topic, 0)
    _house_rows = [
        ("額相", "思维", X["额相"], f"活跃 {'·'.join(map(str,A['peak']))} 时"),
        ("眼相", "焦点", X["眼相"], f"{top_topic} {top_pct*100:.1f}%"),
        ("氣色", "情绪", X["气色"], f"正 {A['pos']} · 负 {A['neg']}"),
        ("口相", "表达", X["口相"], f"日均 {A['daily']} 條"),
        ("骨相", "存在", X["骨相"], f"日均 {A['daily']} 條"),
        ("手相", "创作", X["手相"], f"原创 {A['orig']*100:.0f}%"),
        ("眉相", "提问", X["眉相"], f"问号率 {A['qu']*100:.0f}%"),
    ]
    houses_html = "\n      ".join(
        f'<div class="house h{i+1}"><div class="h-name">{name} · {dim}</div><div class="h-tag">{_term_html(t)}</div><div class="h-val">{val}</div></div>'
        for i, (name, dim, t, val) in enumerate(_house_rows))
    _ck = []
    for _t in [X["额相"], X["骨相"], X["眉相"]]:
        _k = KEY.get(_t, "")
        if _k == "追问": _k = "好问"
        if _k and _k not in _ck: _ck.append(_k)
    center_sub = "·".join(_ck)
    oracle = (f"{X['额相']}主{_hl(KEY[X['额相']])}，{X['眼相']}主{_hl(KEY[X['眼相']])}，{X['气色']}主{_hl(KEY[X['气色']])}。"
              f"{X['口相']}、{X['骨相']}，主{_hl(KEY[X['口相']])}；{X['手相']}主{_hl(KEY[X['手相']])}；{X['眉相']}主{_hl(KEY[X['眉相']])}。"
              f"七相合参：一位{img}。{A['daily']} 条/日的输出节奏，{top_topic} {top_pct*100:.0f}% 的话题浓度，"
              f"{'问号' if X['眉相']=='问眉' else '风格'}里藏着{'追问欲' if X['眉相']=='问眉' else '表达欲'}。")
    data_items = "\n        ".join([
        f'<div class="d-item"><span>发帖频率</span><b>{A["daily"]} 条/日</b></div>',
        f'<div class="d-item"><span>平均篇幅</span><b>{A["avg_len"]} 字</b></div>',
        f'<div class="d-item"><span>原创占比</span><b>{round(A["orig"]*100,1)}%</b></div>',
        f'<div class="d-item"><span>情绪指数</span><b>{emotion}</b></div>',
    ])
    V = {
        "NICKNAME": nick,
        "META": f"微博 {A['n']} 條 · 觀相{A['span']}日 · 丙午年夏",
        "CENTER_SUB": center_sub,
        "HOUSES": houses_html,
        "ORACLE": oracle,
        "DATA_ITEMS": data_items,
        "FORTUNE": rx,
        "FOOT": f"據微博{A['n']}條公開數據推演",
    }
    tpl = open(MINGPAN_TPL, encoding="utf-8").read()
else:
    V = {
        "NICKNAME": nick,
        "REPORT_NO": f"SP-{today.year}-{today.month:02d}{today.day:02d}",
        "COUNT": A["n"],
        "SPAN": A["span"],
        "DATE": f"{today.year}-{today.month:02d}-{today.day:02d} 00:00",
        "CONCL1": concl1,
        "CONCL2": concl2,
        "SUMMARY": summary,
        "DAILY": A["daily"],
        "ORIG": round(A["orig"]*100, 1),
        "AVG_LEN": A["avg_len"],
        "EMOTION": emotion,
        "EMOTION_NOTE": emotion_note,
        "PEAKS": peaks,
        "ROWS": "\n    ".join(rows),
        "RX": rx,
        "RX_LINE": rx_line,
    }
    tpl = open(TEMPLATE, encoding="utf-8").read()
for k, v in V.items():
    tpl = tpl.replace(f"@@{k}@@", str(v))
with open(_a.output, "w", encoding="utf-8") as f:
    f.write(tpl)
_name = "面相星盘" if TEMPLATE_NAME == "mingpan" else "面相诊断书"
print(f"\n✅ {_name}已生成: {_a.output}（{len(tpl)} bytes）", file=sys.stderr)
print(f"面相: {' · '.join(X.values())}", file=sys.stderr)
