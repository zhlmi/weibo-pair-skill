#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微博配对 · 文案层：判词、维度说明、媒婆/场记点评、缘分徽章。

prepare() 从 config.C 读取分析结果，生成全部文案并写回 config.C。
"""
import random
import re

import config


def pct(x):
    return round(x * 100, 1)


def pick(pool):
    return random.choice(pool)


def rhythm_desc(x):
    tags = []
    if x["early"] > 0.25: tags.append("清晨活跃")
    if x["night"] > 0.25: tags.append("夜间活跃")
    if x["early"] <= 0.25 and x["night"] <= 0.25: tags.append("白天型")
    return "、".join(tags)


def prepare():
    C = config.C
    A, B = C["A"], C["B"]
    ha, hb = C["ha"], C["hb"]
    sleep, interest = C["sleep"], C["interest"]
    personality, comm = C["personality"], C["comm"]
    comp, humor = C["comp"], C["humor"]
    circle, fate = C["circle"], C["fate"]
    fate_sig = C["fate_sig"]
    follow_state = C["follow_state"]
    fate_polarity = C["fate_polarity"]
    fate_density = C["fate_density"]
    sleep_hits = C["sleep_hits"]
    overlap, cat_sim = C["overlap"], C["cat_sim"]
    other_posts = C["other_posts"]
    MODE = config.MODE
    IS_SELF = config.IS_SELF
    POLARITY_NOTE = config.POLARITY_NOTE
    OTHER_UID = config.OTHER_UID

    # ---- 对方人称（性别推断：user.gender 'f'→她 / 'm'→他 / 未知→TA）----
    def _other_gender():
        for p in other_posts:
            g = (p.get("user") or {}).get("gender")
            if g in ("m", "f"):
                return g
        try:
            import weibo_api
            d = weibo_api.cli(["users", "show_batch/other", "--uids", str(OTHER_UID), "--output", "json"])
            for u in d.get("users") or []:
                if u.get("gender") in ("m", "f"):
                    return u.get("gender")
        except Exception:
            pass
        return None

    _og = _other_gender()
    OTHER_PRON = "她" if _og == "f" else ("他" if _og == "m" else "TA")
    OTHER_HEAD = "贰 · 她 述" if _og == "f" else ("贰 · 他 述" if _og == "m" else "贰 · 对方 述")

    # ---- 维度文案：按数据分档 + 措辞变体池 ----
    sleep_tag = pick(["高度同步", "同频作息", "生物钟重合"]) if sleep >= 0.7 else (pick(["部分重叠", "错峰同行", "时段交错"]) if sleep >= 0.45 else pick(["错位明显", "时差错开", "两个时区"]))

    shared_topics = '、'.join(set(A['话题']['top']) & set(B['话题']['top'])) or "无明显共同话题"
    if interest >= 0.9:
        interest_tag = pick(["灵魂共鸣", "话题共振", "复制粘贴级默契", "同频共振"])
        interest_note = pick(["话题分布几乎复制粘贴", "你俩的微博像同一个人的两个账号在发", "聊起天来话题根本不用预热", f"{OTHER_PRON}发的东西你基本都在追"])
    elif interest >= 0.7:
        interest_tag = pick(["话题相投", "聊得来", "有共同语言"])
        interest_note = pick(["有共同话题打底，各有各的侧重", "能聊到一起，也各有盲区", "话题重合度不错，够聊一阵子"])
    else:
        interest_tag = pick(["话题各半", "各聊各的", "交集有限"])
        interest_note = pick(["共同话题不多，靠新鲜感撑着", "话题版图各占一头，交集要刻意找"])

    ea, eb = A['情绪']['avg'], B['情绪']['avg']
    if ea < 0.25 and eb < 0.25:
        per_tag = pick(["稳定 × 稳定", "两杯温水", "情绪同温层", "波澜不惊二人组"])
        per_note = pick(["两个情绪稳定的人，像两杯温水", "都是低情绪振幅体质，吵不起来", "波澜不惊，互相传染淡定"])
    elif ea >= 0.25 and eb >= 0.25:
        per_tag = pick(["热情 × 热情", "两团火", "情绪外放二人组"])
        per_note = pick(["两个情绪外放的人，热闹但容易互相抢话", "都是直给型，情绪写在脸上"])
    else:
        per_tag = pick(["互补温差", "冷静 × 热烈"])
        per_note = f"一个热烈一个冷静（情绪 {max(ea, eb):.3f} vs {min(ea, eb):.3f}），一热一冷互补着正好"

    comm_tag = pick(["可对话", "频道相通", "聊得来", "接得上话"])

    fa, la = A['作息']['daily'], A['创作']['avg_len']
    fb, lb = B['作息']['daily'], B['创作']['avg_len']
    comp_ratio = fb / fa if fa else 0
    comp_tag = pick(["量级互补", "一个顶俩", "节奏互补"]) if (comp_ratio >= 1.5 or comp_ratio <= 0.67) else pick(["节奏同步", "半斤八两"])

    exa, exb = A['表达']['ex'], B['表达']['ex']
    if abs(exa - exb) > 0.04:
        humor_tag = pick(["冷面 × 热情", "反差萌", "冰火两重天"])
        humor_note = pick(["冷面配热情，互补幽默", "一个负责冷场一个负责热场", "感叹号差就是你们笑点差的温度计"])
    else:
        humor_tag = pick(["笑点同频", "一路人", "都爱冷幽默"])
        humor_note = pick(["都走冷幽默路线", "笑点在同一频道", "笑点上没有代沟"])

    if circle >= 0.7:
        circle_tag = pick(["科技圈高度重合", "同一个圈子", "关注同频", "圈内人"])
        if not IS_SELF:
            circle_note = "内容圈层近似（A×B 关注列表 API 受限）。发的内容高度重合，是圈内人"
        else:
            circle_note = pick(["关注列表长在同一棵树上", "品类重合度高，是圈内人", "你们的雷达扫的是同一片海域"])
    else:
        circle_tag = pick(["圈子各半", "平行圈层", "交集有限"])
        circle_note = pick(["圈子只有少量重叠", "关注的版图各占一头", "雷达扫的是不同海域"])

    # 缘分：互动量级徽章（直接转发次数分档）
    dr, ch = fate_sig['direct_repost'], fate_sig['chain'] + fate_sig['chain_tech']
    if dr >= 20:
        fate_tag = "🔥 深度互转"
        fate_note = pick([
            f"直接转发 {dr} 次 · 转发链共现 {ch} 条。这不是互动，是日常。",
            f"直接转发 {dr} 次 · 转发链共现 {ch} 条。互相转发都快成连载了。",
            f"直接转发 {dr} 次 · 转发链共现 {ch} 条。转发列表里对方的名字出现得比谁都勤。",
        ])
    elif dr >= 10:
        fate_tag = "⚡ 强互动"
        fate_note = pick([
            f"直接转发 {dr} 次 · 转发链共现 {ch} 条。互动频繁，含金量高。",
            f"直接转发 {dr} 次 · 转发链共现 {ch} 条。有来有往，已经形成习惯。",
            f"直接转发 {dr} 次 · 转发链共现 {ch} 条。技术圈转发克制，这个频率是真认可。",
        ])
    elif dr >= 5:
        fate_tag = "💬 高频互动"
        fate_note = pick([
            f"直接转发 {dr} 次 · 转发链共现 {ch} 条。互相捧场已成习惯。",
            f"直接转发 {dr} 次 · 转发链共现 {ch} 条。隔三差五就转一次，话不多但都在。",
        ])
    elif dr >= 1 or ch >= 3:
        fate_tag = "✨ 有互动痕迹"
        fate_note = pick([
            f"直接转发 {dr} 次 · 转发链共现 {ch} 条。有来有往，尚浅但真实。",
            f"直接转发 {dr} 次 · 转发链共现 {ch} 条。互动不算多，但方向是对的。",
        ])
    else:
        fate_tag = "🤝 暂无交集"
        fate_note = pick(["未发现直接互动，可能是平行宇宙里的两个人。", "零转发零共现。至少目前，你们活在各自的微博里。"])

    # 互动极性标注（v1.4.3：--polarity-note 用户事实优先；v1.7.0 密度句）
    if POLARITY_NOTE:
        fate_note += f" {POLARITY_NOTE}。互动是日常，不是客套。"
    elif fate_polarity == "negative":
        fate_tag = "⚠️ " + fate_tag
        fate_note += " 互动虽多但偏负面（对线/开骂）。数字高不代表登对，先别急着处对象。"
    elif fate_polarity == "mixed":
        fate_note += " 互动有来有往但夹杂摩擦，默契还得慢慢养。"
    fate_note += f" 互动密度 {fate_density:.1f} 次/百条。"

    fate_dim_name = "互动深度" if MODE == "business" else "缘分指数"
    dims = [
        ("作息匹配", sleep, f"峰值 A{ha} vs B{hb}。3 个活跃高峰对上 {sleep_hits:g} 个（±1h 内算重合），峰值重合率 {pct(sleep)}%", sleep_tag),
        ("兴趣契合", interest, f"共同话题：{shared_topics}。{interest_note}", interest_tag),
        ("性格互补", personality, f"A 情绪 {ea} vs B {eb}。{per_note}", per_tag),
        ("沟通风格", comm, f"A {A['互动']['style']}（原创{pct(A['创作']['orig'])}%）vs B {B['互动']['style']}（原创{pct(B['创作']['orig'])}%）", comm_tag),
        ("创作互补", comp, f"A 日均 {fa} 条·{la}字 vs B 日均 {fb} 条·{lb}字", comp_tag),
        ("笑点匹配", humor, f"A 感叹号率 {exa} vs B {exb}。{humor_note}", humor_tag),
        ("圈子兼容", circle, f"降级估算：UID交集率 {pct(overlap)}% / 品类相似度 {pct(cat_sim)}%，取 max。{circle_note}", circle_tag),
        (fate_dim_name, fate, f"{fate_note} 互关 {fate_sig['follow']}（{'用户确认' if follow_state == 'confirmed' else '检测到' if follow_state == 'found' else 'API 受限' if follow_state == 'n/a' else '未覆盖'}）", fate_tag),
    ]

    # ---- 按模式生成 dims HTML（三套结构）----
    def build_dims_html():
        if MODE == "couple":
            return "".join(f'''<div class="dim{f' dim-fate' if n == fate_dim_name else ''}"><div class="d-name">{n}</div><div class="d-bar"><div class="d-fill" style="width:{pct(s)}%"></div></div><div class="d-pct">{pct(s)}<small>%</small></div><div class="d-note">{dt}</div></div>''' for n, s, dt, t in dims)
        elif MODE == "business":
            return "".join(f'''<div class="dim{f' dim-fate' if n == fate_dim_name else ''}"><div class="d-name">{n}</div><div class="d-track"><div class="d-fill" style="width:{pct(s)}%"></div></div><div class="d-pct">{pct(s)}<small>%</small></div><div class="d-note">{dt}</div></div>''' for n, s, dt, t in dims)
        else:
            return "".join(f'''<div class="level{f' l-hot' if n == fate_dim_name else ''}"><div class="l-name">{n}</div><div class="l-track"><div class="l-fill" style="width:{pct(s)}%"></div></div><div class="l-val">{pct(s)}<small>%</small></div><div class="l-note">{dt}</div></div>''' for n, s, dt, t in dims)

    def build_comp_advice(A, B):
        """创作互补点评（朋友模式）：按双方实际频率/均长动态生成"""
        fa, la = A['作息']['daily'], A['创作']['avg_len']
        fb, lb = B['作息']['daily'], B['创作']['avg_len']
        ratio = fb / fa if fa else 0
        if ratio >= 1.5:
            lead = f"{OTHER_PRON}的输出量是你的 {ratio:.1f} 倍，一个人就是一支刷屏军团"
        elif ratio <= 0.67:
            lead = f"你的输出量是{OTHER_PRON}的 {1 / ratio:.1f} 倍，你才是更活跃的那个"
        else:
            lead = "你们输出量相当，节奏半斤八两"
        if lb > la * 1.2:
            depth = f"{OTHER_PRON}还更爱写长文（均长 {lb:.0f} 字 vs 你的 {la:.0f} 字）"
        elif la > lb * 1.2:
            depth = f"你更爱写长文（均长 {la:.0f} 字 vs {OTHER_PRON}的 {lb:.0f} 字）"
        else:
            depth = "你们都是短平快选手，字数不相上下"
        tail = pick(["真做搭档不用强行合体。各打各的节奏、互相转发捧场，反而更舒服。",
                     f"组队的话一个负责量一个负责精，但别指望{OTHER_PRON}降速陪你。",
                     "做朋友就别比产量了，一个刷屏一个点赞，各得其乐。",
                     f"想合作就错峰出内容，你补{OTHER_PRON}空档，{OTHER_PRON}补你周末。"])
        return f"创作节奏：{lead}；{depth}。{tail}"

    # 媒婆点评：按模式（情侣暧昧 / 朋友轻松 / 商务克制）× 数据分档 × 变体池
    ratio = fb / fa if fa else 0
    hi_side = "对方" if ratio >= 1 else "你"
    hi_num = f"{ratio:.1f}" if ratio >= 1 else f"{1 / ratio:.1f}"

    def sleep_advice():
        if sleep >= 0.7:
            return f"作息高度同步（{pct(sleep)}%）。你 {ha} 点在线{OTHER_PRON} {hb} 点也在线，想聊随时抓得到人，这是最难得的默契。"
        if sleep >= 0.45:
            if MODE == "couple":
                return pick([
                    f"兴趣同频到 {pct(interest)}%，唯一的小摩擦在作息（{pct(sleep)}%）。你 {ha} 点派、{OTHER_PRON} {hb} 点派，把对话框当留言板，想到了就写、看到就回，错峰也是浪漫。",
                    f"一个午后一个清晨（同步率 {pct(sleep)}%），像两个时区的人。但正因为不黏腻，每次聊天都值得期待。",
                    f"作息部分重叠（{pct(sleep)}%）：{ha} 点派和 {hb} 点派，留言就是你们的暗号，隔空也能把日子过到一起。",
                ])
            if MODE == "business":
                return pick([
                    f"协作窗口：双方活跃时段重叠 {pct(sleep)}%（峰值 {ha} vs {hb}），关键沟通建议安排在共同在线时段，其余用异步留言对齐。",
                    f"时段匹配度 {pct(sleep)}%：{ha} 点派与 {hb} 点派，实时碰面窗口有限，靠结构化异步留言反而更高效。",
                ])
            return pick([
                f"同频度 {pct(interest)}% 摆在这，唯一的摩擦是作息（{pct(sleep)}%）：你 {ha} 点派、{OTHER_PRON} {hb} 点派，把对话框当留言板，想到了就写、看到就回。",
                f"兴趣这么合（{pct(interest)}%），可惜上线时段只重叠一半（{pct(sleep)}%）：峰值 {ha} vs {hb}，你们像两个时区的人，靠异步沟通续命。",
                f"不是不热情，是时差。作息部分重叠（{pct(sleep)}%），{ha} 点派和 {hb} 点派之间，留言就是你们的暗号。",
                f"整体很合拍（{pct(interest)}% 兴趣 + {pct(personality)}% 性格），唯一要适应的是作息（{pct(sleep)}%）：{ha} 点 vs {hb} 点，错峰聊天，谁也不用迁就谁。",
                f"兴趣同频到 {pct(interest)}%，作息却只对上一半（{pct(sleep)}%）。{ha} 点派和 {hb} 点派，建议把微信当邮箱用：留言即可，看到就回。",
            ])
        if MODE == "couple":
            return pick([
                f"作息几乎错开（{pct(sleep)}%）：你 {ha} 点活跃{OTHER_PRON} {hb} 点活跃，像两个星球的人。但留言不会丢，缘分靠时差也能续。",
                f"时差错位（{pct(sleep)}%）：{ha} 与 {hb} 几乎不碰面，线上互关的两个人过着两个白天，约实时不如约留言。",
            ])
        if MODE == "business":
            return pick([
                f"时段重叠仅 {pct(sleep)}%：{ha} 与 {hb} 几乎无交集，实时协作成本高，建议明确异步沟通机制（留言 + 定期对齐）。",
                f"作息错位明显（{pct(sleep)}%）：双方活跃时段互不重叠，合作需靠结构化异步协作，减少实时依赖。",
            ])
        return pick([
            f"最大的坎在作息（{pct(sleep)}%）：一个 {ha} 点活跃一个 {hb} 点活跃，想实时聊天基本靠缘分，留言板模式是唯一出路。",
            f"时差错位明显（{pct(sleep)}%），{ha} 与 {hb} 几乎不碰面。线上互关的两个人，过的是两个白天。",
            f"其他维度都说得过去，唯独作息（{pct(sleep)}%）像两个星球：你醒着{OTHER_PRON}睡，{OTHER_PRON}醒着你睡。别约实时，约留言。",
            f"作息 {pct(sleep)}% 错位明显，{ha} vs {hb} 两个时段几乎不碰面。把微信当邮箱使，是你们唯一的沟通方式。",
        ])

    def comp_advice():
        if MODE == "couple":
            if ratio >= 1:
                return pick([
                    f"创作节奏差得很妙：{OTHER_PRON}的输出量是你的 {hi_num} 倍，一个人就是一支刷屏军团。{OTHER_PRON}制造热闹，你接住热闹，正好互补。",
                    f"{OTHER_PRON}刷屏你追更（输出量比 {hi_num}:1），{OTHER_PRON}把日子过成连续剧，你负责点赞，节奏不同但都在。",
                ])
            return pick([
                f"创作节奏差得很妙：你的输出量是{OTHER_PRON}的 {hi_num} 倍，一个人就是一支刷屏军团。你制造热闹，{OTHER_PRON}接住热闹，正好互补。",
                f"你刷屏{OTHER_PRON}追更（输出量比 {hi_num}:1），你把日子过成连续剧，{OTHER_PRON}负责点赞，节奏不同但都在。",
            ])
        if MODE == "business":
            return pick([
                f"产能结构：{hi_side}输出量是{hi_num}倍（日均 {fa:.1f} vs {fb:.1f} 条），建议分工。量大的负责选题引流，量小的负责深度打磨，各取所长。",
                f"内容产能差异明显（日均 {fa:.1f} 条 vs {fb:.1f} 条），合作时按产能分配职责，避免一方闲置、一方过载。",
            ])
        return build_comp_advice(A, B)

    def circle_advice():
        if circle >= 0.7 and not IS_SELF:
            return pick([
                f"圈子兼容 {pct(circle)}%（内容圈层近似）：发的内容高度重合，是同一个圈子里的人。先从评论区互关开始，然后互相转发，这就是现代友情。",
                f"圈子兼容 {pct(circle)}%（内容圈层近似）：微博长在同一棵科技树上。圈内人见面，一个转发就是递名片，别端着。",
                f"圈子兼容 {pct(circle)}%（内容圈层近似）：聊的内容高度同频，大概率在彼此的评论区打过照面。别客气，直接互关，下一轮转发就有你。",
            ])
        if circle >= 0.7:
            if MODE == "couple":
                return pick([
                    f"圈子兼容 {pct(circle)}%：你们的关注列表长在同一棵树上。缘分藏在你共同关注的每一条里，先从互关开始。",
                    f"圈子兼容 {pct(circle)}%：同一个圈子里的人，大概率早就在别人的评论区打过照面。这种缘分，别错过。",
                ])
            if MODE == "business":
                return pick([
                    f"人脉重叠 {pct(circle)}%（品类相似度 {pct(cat_sim)}%）：关注圈高度重合，合作时共同话题充足、破冰成本低，人脉可互相导流。",
                    f"行业圈层重合度 {pct(circle)}%：双方关注品类接近，意味着信息源高度相似，合作共识容易建立。",
                ])
            return pick([
                f"圈子兼容 {pct(circle)}%：你们的关注列表品类高度重合，是同一个圈子里的人。先从评论区互关开始，然后互相转发，这就是现代友情。",
                f"圈子兼容 {pct(circle)}%：关注列表都长在同一棵科技树上。圈内人见面，一个转发就是递名片，别端着。",
                f"圈子兼容 {pct(circle)}%：你们大概率在别人的评论区打过照面。别客气，直接互关，下一轮转发就有你。",
            ])
        if MODE == "couple":
            return pick([
                f"圈子兼容只有 {pct(circle)}%：关注版图各占一头。但正因圈子不同，聊天才总有新鲜事可讲，互补着来。",
                f"圈子兼容 {pct(circle)}%：你们活在不同海域，靠兴趣交集（{pct(interest)}%）搭上了线。这份相遇本身就更珍贵。",
            ])
        if MODE == "business":
            return pick([
                f"人脉重叠仅 {pct(circle)}%：关注圈交集有限，合作需主动拓展共同信息源，建议互相推荐优质账号/资源建立共识。",
                f"圈层重合度 {pct(circle)}%：双方信息源差异大，初期对齐成本较高，可从对方领域的热点话题切入破冰。",
            ])
        return pick([
            f"圈子兼容只有 {pct(circle)}%：关注版图各占一头，想熟起来得先找共同话题，从转发对方感兴趣的内容开始。",
            f"圈子兼容 {pct(circle)}%：目前是平行圈层，靠兴趣交集（{pct(interest)}%）还能搭上话，多转发多互动慢慢就熟了。",
        ])

    advice = [sleep_advice(), comp_advice(), circle_advice()]

    # ---- 按模式生成 adv HTML（三套结构）----
    if MODE == "couple":
        adv_html = "".join(f'<div class="advice"><span class="a-num">{i + 1}</span><p>{a}</p></div>' for i, a in enumerate(advice))
    elif MODE == "business":
        cn = "一二三"
        adv_html = "".join(f'<div class="advice"><div class="a-num">{cn[i]}</div><p>{a}</p></div>' for i, a in enumerate(advice))
    else:
        tags = ["场记 01 · 时差", "场记 02 · 量级", "场记 03 · 圈子"]
        adv_html = "".join(f'<div class="note"><span class="n-tag">{tags[i]}</span><p>{a}</p></div>' for i, a in enumerate(advice))

    # ---- 总评 / 卡司 / 印章 ----
    total = C["total"]
    if total >= 80:
        verdict = ("<em>天作之合</em>，实至名归" if MODE == "couple"
                   else "合作默契，<em>开局即巅峰</em>" if MODE == "business"
                   else "缘分已深，<em>堪称佳偶</em>")
    elif total >= 70:
        verdict = "志趣相投，<em>缘分不浅</em>"
    elif total >= 60:
        verdict = "有缘人，<em>尚需磨合</em>"
    else:
        verdict = "<em>缘分尚浅</em>，各自安好"

    if ratio >= 1.5:
        my_char, other_char = "克制短打", "刷屏军团"
    elif ratio <= 0.67:
        my_char, other_char = "刷屏军团", "克制短打"
    else:
        my_char, other_char = "同频选手", "同频选手"

    fate_tag_plain = re.sub(r"^[^\u4e00-\u9fa5]*", "", fate_tag)
    seal_tag = "深度互转" if (dr >= 20 and fate_polarity != "negative") else (fate_tag_plain or "缘分")

    dims_html = build_dims_html()

    strong_name, strong_val = max(((n, s) for n, s, *_ in dims), key=lambda x: x[1])
    weak_name, weak_val = min(((n, s) for n, s, *_ in dims), key=lambda x: x[1])

    # ---- 写回上下文 ----
    C.update({
        "OTHER_PRON": OTHER_PRON, "OTHER_HEAD": OTHER_HEAD,
        "dims": dims, "dims_html": dims_html, "advice": advice, "adv_html": adv_html,
        "fate_dim_name": fate_dim_name, "fate_tag": fate_tag, "fate_tag_plain": fate_tag_plain,
        "verdict": verdict, "seal_tag": seal_tag,
        "strong_name": strong_name, "strong_val": strong_val,
        "weak_name": weak_name, "weak_val": weak_val,
        "ratio": ratio, "hi_side": hi_side, "hi_num": hi_num,
        "fa": fa, "la": la, "fb": fb, "lb": lb,
        "my_char": my_char, "other_char": other_char,
        "dr": dr, "ch": ch,
    })
