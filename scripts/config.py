#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微博配对 · 全局配置：命令行参数解析 + 跨模块共享的运行时上下文。

其他模块统一 `import config` 后通过 config.XXX 访问（动态属性，保持最新值）。
C 是分析结果上下文（主流程逐步填充，文案/渲染层读取）。
"""
import argparse, os

_ap = argparse.ArgumentParser(description="微博配对完整链路（含降级圈子兼容）")
_ap.add_argument("--other-uid", required=True, help="对方微博 UID")
_ap.add_argument("--my-uid", required=True, help="我方微博 UID")
_ap.add_argument("--count", type=int, default=100, help="对方采样条数（默认100，原创博主建议300+）")
_ap.add_argument("--my-count", type=int, default=100, help="我方采样条数（默认100走weibo-skill免费；>100走weibo-cli user_timeline/biz）")
_ap.add_argument("--output", default=None, help="HTML 输出路径（缺省：<缓存目录>/weibo-pair-match.html）")
_ap.add_argument("--cache-dir", default=os.environ.get("WEIBO_PAIR_CACHE", "/var/minis/workspace"), help="缓存目录（缺省：$WEIBO_PAIR_CACHE 或 /var/minis/workspace）")
_ap.add_argument("--my-nick", default=None, help="我方昵称（缺省自动从 API 获取）")
_ap.add_argument("--other-nick", default=None, help="对方昵称（缺省自动从 API 获取）")
_ap.add_argument("--mutual-follow", action="store_true", help="用户确认双方互关（自动检测受 count 上限 20 限制，翻页找不到时由用户确认兜底）")
_ap.add_argument("--mode", choices=["couple", "friend", "business"], default="friend",
                 help="方向：couple=情侣（相亲角报纸）/ friend=朋友（电影片尾）/ business=商务（数据杂志），默认 friend")
_ap.add_argument("--my-role", default=None, help="我方身份描述（缺省按话题自动推断，如：内容创作者）")
_ap.add_argument("--other-role", default=None, help="对方身份描述（缺省按话题自动推断）")
_ap.add_argument("--polarity-note", default="", help="用户确认的关系性质文案（如'线下老朋友'），跳过极性打折并用此文案覆盖摩擦判词")
_ap.add_argument("--on-short", choices=["ask", "continue", "abort"], default="ask",
                 help="数据不足目标量时的策略：ask=询问用户（默认；非交互环境退出码3）/ continue=用现有数据继续 / abort=中止（退出码2）")
def parse():
    """解析命令行参数（仅 pair.py 入口显式调用；其他模块 import config 无副作用）"""
    _a = _ap.parse_args()
    globals().update({
        "MUTUAL_FOLLOW": _a.mutual_follow,
        "MY_UID": _a.my_uid,
        "OTHER_UID": _a.other_uid,
        "COUNT": _a.count,
        "MY_COUNT": _a.my_count,
        "OUT_HTML": _a.output,
        "MY_NICK": _a.my_nick,
        "OTHER_NICK": _a.other_nick,
        "MODE": _a.mode,
        "MY_ROLE_ARG": _a.my_role,
        "OTHER_ROLE_ARG": _a.other_role,
        "POLARITY_NOTE": _a.polarity_note,
        "ON_SHORT": _a.on_short,
        "CACHE_DIR": _a.cache_dir,
    })
    if not globals().get("OUT_HTML") or globals()["OUT_HTML"] == "None":
        globals()["OUT_HTML"] = f"{_a.cache_dir}/weibo-pair-match.html"
    globals()["MODE_CN"] = {"couple": "情侣", "friend": "朋友", "business": "商务"}[_a.mode]
    globals()["LOGIN_CACHE"] = f"{_a.cache_dir}/pair_login_uid.json"

# ---- 路径（不依赖参数，import 即可用；CACHE_DIR 在 parse() 后确定）----
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = "/var/minis/workspace"  # parse() 后会被 --cache-dir 覆盖
LOGIN_CACHE = None  # parse() 后设置

# ---- 运行时上下文（分析后填充，供文案/渲染层读取）----
C = {}

# 以下变量由主流程逐步设置：
# LOGIN_UID / IS_SELF / FOLLOWING_CACHE / OTHER_CACHE / MY_CACHE / ACTIVE_CACHE
# MY_NICK / OTHER_NICK（可能被 API 补全）
# A / B / ha / hb / sleep / interest / personality / comm / comp / humor / circle
# fate / fate_sig / fate_details / follow_state / fate_polarity / fate_pos / fate_neg / fate_third / fate_density
# dr / ch / ratio / fa / la / fb / lb / hi_side / hi_num / OTHER_PRON / OTHER_HEAD
# my_span / other_span / my_role / other_role / my_rhythm / other_rhythm / my_tags / other_tags
# my_char / other_char / dims / total / advice / adv_html / verdict / strong_name / strong_val / weak_name / weak_val
