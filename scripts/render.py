#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微博配对 · 渲染层：三方向模板（couple 相亲角 / business 数据杂志 / friend 电影片尾）变量组装与输出。"""
import datetime, os, sys

import config
import weibo_api
import copywriter


TEMPLATE_DIR = os.path.join(config.SKILL_DIR, "templates")
TEMPLATES = {
    "couple": f"{TEMPLATE_DIR}/couple.html",
    "business": f"{TEMPLATE_DIR}/business.html",
    "friend": f"{TEMPLATE_DIR}/friend.html",
}


def render(vars_dict):
    tpl = open(TEMPLATES[config.MODE], encoding="utf-8").read()
    for k, v in vars_dict.items():
        tpl = tpl.replace(f"@@{k}@@", str(v))
    return tpl


def infer_role(topics):
    t = set(topics)
    if t & {"影视影像"}: return "影视从业者"
    if t & {"科技AI"}: return "科技博主"
    if t & {"工作创作"}: return "内容创作者"
    if t & {"生活日常"}: return "生活记录者"
    return "微博活跃用户"


def span_days(posts):
    times = [weibo_api.parse_time(p.get("created_at", "")) for p in posts]
    times = [t for t in times if t]
    return (max(times) - min(times)).days if len(times) >= 2 else 0


def person_tags(x):
    tags = []
    tags.append(("hot", "高频") if x['作息']['daily'] > 2 else ("", "低频"))
    tags.append(("", "冷面") if x['表达']['ex'] < 0.1 else ("", "热情"))
    if x['作息']['early'] > 0.25: tags.append(("hot", "早起鸟"))
    elif x['作息']['night'] > 0.25: tags.append(("", "夜猫子"))
    else: tags.append(("", "白天型"))
    return "".join(f'<i class="{c}">{t}</i>' for c, t in tags)


def run(scores, total):
    C = config.C
    A, B = C["A"], C["B"]
    ha, hb = C["ha"], C["hb"]
    circle = C["circle"]
    fate = C["fate"]
    dr, ch = C["dr"], C["ch"]
    follow_state = C["follow_state"]
    interest = C["interest"]
    my_posts, other_posts = C["my_posts"], C["other_posts"]
    MODE = config.MODE
    pct = copywriter.pct
    pick = copywriter.pick

    d = datetime.date.today()
    my_span, other_span = span_days(my_posts), span_days(other_posts)
    my_role = config.MY_ROLE_ARG or infer_role(A['话题']['top'])
    other_role = config.OTHER_ROLE_ARG or infer_role(B['话题']['top'])
    my_rhythm, other_rhythm = copywriter.rhythm_desc(A['作息']), copywriter.rhythm_desc(B['作息'])
    my_tags, other_tags = person_tags(A), person_tags(B)

    V = {}
    V["MY_NICK"] = config.MY_NICK; V["OTHER_NICK"] = config.OTHER_NICK
    V["OTHER_HEAD"] = C["OTHER_HEAD"]
    V["MY_ROLE"] = my_role; V["OTHER_ROLE"] = other_role
    V["MY_PEAKS"] = "、".join(map(str, ha)); V["OTHER_PEAKS"] = "、".join(map(str, hb))
    V["MY_TOPICS"] = " / ".join(A['话题']['top']); V["OTHER_TOPICS"] = " / ".join(B['话题']['top'])
    V["MY_MOOD"] = A['情绪']['mood']; V["OTHER_MOOD"] = B['情绪']['mood']
    V["MY_ORIG"] = pct(A['创作']['orig']); V["OTHER_ORIG"] = pct(B['创作']['orig'])
    V["MY_DAILY"] = f"{A['作息']['daily']:.2f}".rstrip("0").rstrip("."); V["OTHER_DAILY"] = f"{B['作息']['daily']:.2f}".rstrip("0").rstrip(".")
    V["MY_LEN"] = A['创作']['avg_len']; V["OTHER_LEN"] = B['创作']['avg_len']
    V["MY_TAGS"] = my_tags; V["OTHER_TAGS"] = other_tags
    V["MY_RHYTHM"] = my_rhythm; V["OTHER_RHYTHM"] = other_rhythm
    V["MY_CHAR"] = C["my_char"]; V["OTHER_CHAR"] = C["other_char"]
    V["TOTAL"] = f"{total:.1f}"
    V["DIMS"] = C["dims_html"]
    V["ADVS"] = C["adv_html"]
    V["DATE_CN"] = "丙午年·夏"
    V["DATE_SHORT"] = f"{d.year}·{d.month:02d}·{d.day:02d}"
    V["MODE_EN"] = {"couple": "COUPLING", "friend": "FRIENDSHIP", "business": "PARTNERSHIP"}[MODE]
    V["MY_COUNT"] = len(my_posts); V["OTHER_COUNT"] = len(other_posts)
    V["SEAL_TAG"] = C["seal_tag"]
    V["VRL_TAG"] = "二人同圈 · 缘分可期" if circle >= 0.7 else "圈子相远 · 缘分待续"
    V["VERDICT"] = C["verdict"]
    V["VERDICT_SUB"] = (f"{C['strong_name']}（{pct(C['strong_val'])}%）是你们最稳的支点，{C['weak_name']}（{pct(C['weak_val'])}%）是最大的变量。"
                        + pick(["有支点就散不了，变量慢慢磨", "支点够硬，剩下的交给相处", "底子有了，变量就交给时间"]))
    V["FATE_DR"] = dr; V["FATE_CH"] = ch; V["FATE_RATIO"] = C["hi_num"]
    V["FATE_LINE1"] = C["fate_tag_plain"] + " · " + pick(["这不是互动，是日常", "互相转发都快成连载了", "转发列表里对方的名字出现得比谁都勤"])
    _fl_users, _fl_src = weibo_api.load_following()
    V["FATE_LINE2"] = f"转发链共现 {ch} 条 · 互关{'实锤' if follow_state in ('found', 'confirmed') else 'API 受限' if follow_state == 'n/a' else '未覆盖'}（关注列表 {len(_fl_users or [])} 人）"
    V["V_LINE"] = "互动深度显著 · 合作基础扎实" if fate >= 0.9 else "互动有来有往 · 尚可深化"
    V["V_SUB"] = ("技术圈转发克制：互转核心内容，含金量高于泛娱乐圈的同等行为"
                  if set(A['话题']['top'] + B['话题']['top']) & {"影视影像", "科技AI"}
                  else "互动含金量排序：直接转发 > 转发链共现 > 点赞。转发是最高的认可")
    V["VOL"] = f"{d.month:02d}"
    V["HERO_TITLE"] = f"{'高频' if A['作息']['daily'] >= 10 else '中频' if A['作息']['daily'] >= 3 else '低频'}×{'高频' if B['作息']['daily'] >= 10 else '中频' if B['作息']['daily'] >= 3 else '低频'} 协作可行性评估"
    _interest_lede = "双方话题高度重合" if interest >= 0.7 else ("双方话题有交集" if interest >= 0.45 else "双方话题版图各占一头")
    _interact_lede = f"互动频繁（直接转发 {dr} 次）" if dr >= 10 else (f"有一定互动（直接转发 {dr} 次）" if dr >= 1 else "暂无直接互动信号")
    _concl_lede = "具备建立稳定协作关系的基础" if total >= 70 else ("具备协作潜质，尚需磨合" if total >= 60 else "协作基础尚薄，建议谨慎评估")
    V["LEDE"] = (f"基于公开微博采样（我方 {len(my_posts)} 条 · 对方 {len(other_posts)} 条，覆盖我方 {my_span} 天 · 对方 {other_span} 天），"
                 f"从作息、兴趣、性格、沟通、创作、笑点、圈子、互动八个维度评估协作适配度。"
                 f"综合得分 {total:.1f}/100。{_interest_lede}（兴趣契合 {pct(interest)}%），{_interact_lede}，{_concl_lede}。")
    V["TITLE_CN"] = "缘 分 指 数"
    V["TITLE_EN"] = "A FRIENDSHIP IN TWO TIMELINES"
    V["TC"] = f"00:{d.month:02d}:{d.day:02d}:22"
    V["SPAN"] = f"{min(my_span, other_span)}–{max(my_span, other_span)} 天"

    html = render(V)
    with open(config.OUT_HTML, "w") as f:
        f.write(html)
    print(f"\n✅ HTML 已生成: {config.OUT_HTML}（{len(html)} bytes）", file=sys.stderr)
