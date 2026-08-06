#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微博配对 · 数据获取层：weibo-cli 封装、登录检测、时间线采集、断点续传、缓存读写。"""
import json, os, re, sys, subprocess, datetime

import config


def cli(args):
    """调用 weibo-cli（继承 os.environ 保证 WEIBO_CLI_TOKEN 可用）"""
    env = dict(os.environ); env["NODE_OPTIONS"] = ""
    r = subprocess.run(["weibo-cli"] + args, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"weibo-cli failed: {r.stderr[-300:]}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"non-JSON: {r.stdout[-300:]}")


def parse_time(s):
    try:
        return datetime.datetime.strptime(s, '%a %b %d %H:%M:%S +0800 %Y')
    except Exception:
        return None


def get_login_uid():
    """当前登录用户 UID（friends/biz、weibo-skill 只能操作登录用户本人，A×B 配对需区分）。"""
    try:
        if os.path.exists(config.LOGIN_CACHE):
            d = json.load(open(config.LOGIN_CACHE))
            if d.get("uid"): return d["uid"]
        d = cli(["users", "show/biz", "--output", "json"])
        uid = None
        for u in (d.get("users") or [d]):
            if u.get("id"): uid = str(u["id"]); break
        if uid:
            json.dump({"uid": uid, "fetched_at": str(datetime.datetime.now())}, open(config.LOGIN_CACHE, "w"))
        return uid
    except Exception as e:
        print(f"  ⚠️ 登录用户检测失败: {str(e)[:80]}（按本人配对处理）", file=sys.stderr)
        return None


def load_following():
    """返回 (users, source)。优先读缓存；无缓存则 friends/biz 翻页拉取（最多10页≈200人）并落盘。
    限流/失败时返回 (None, 'error')，由调用方降级处理。"""
    if os.path.exists(config.FOLLOWING_CACHE):
        try:
            d = json.load(open(config.FOLLOWING_CACHE))
            if d.get("users"):
                return d["users"], "cache"
        except Exception:
            pass
    users, seen, page = [], set(), 1
    try:
        while page <= 10:
            d = cli(["friendships", "friends/biz", "--count", "20", "--page", str(page), "--output", "json"])
            batch = d.get("users") or []
            if not batch:
                break
            for u in batch:
                if u.get("id") not in seen:
                    seen.add(u["id"]); users.append(u)
            page += 1
    except Exception as e:
        print(f"  ⚠️ 关注列表获取失败: {str(e)[:120]}（圈子兼容与互关检测降级为无）", file=sys.stderr)
        return None, "error"
    if users:
        json.dump({"users": users, "fetched_at": str(datetime.datetime.now())},
                  open(config.FOLLOWING_CACHE, "w"), ensure_ascii=False)
    return users, "fresh"


def fetch_timeline(uid, target, own=False, resume_from=None, label=""):
    """拉取时间线，支持断点续传：中途限流/失败时保留已抓数据返回（调用方落盘），
    下次重跑传入 resume_from 从缓存末尾 max_id 继续。"""
    posts = list(resume_from or [])
    seen = {p.get("id") for p in posts if p.get("id")}
    max_id = posts[-1]["id"] if posts else None
    page = 0
    while len(posts) < target and page < 30:
        if own:
            args = ["statuses", "user_timeline/biz", "--count", "20", "--output", "json"]
        else:
            args = ["statuses", "user_timeline/other", "--uid", uid, "--count", "20", "--output", "json"]
        if max_id: args += ["--max_id", str(max_id)]
        try:
            d = cli(args)
        except Exception as e:
            print(f"  ⚠️ [{label}] 抓取中断（{str(e)[:90]}），已抓 {len(posts)} 条并落盘，下次自动续传", file=sys.stderr)
            break
        sts = d.get("statuses") or []
        if not sts: break
        new = 0
        for s in sts:
            if s.get("id") not in seen:
                seen.add(s["id"]); posts.append(s); new += 1
        if new == 0:
            break  # 翻到底（全是重复）
        max_id = posts[-1]["id"]; page += 1
        print(f"  page {page}: +{new}, total {len(posts)}", file=sys.stderr)
    return posts


def confirm_short(label, got, want):
    """数据不足目标量时的策略：ask（默认，交互询问；非交互环境退出码 3）/ continue / abort（退出码 2）。
    只在本次新抓取后调用（缓存命中视为用户已接受现状，不询问）。"""
    if got >= want * 0.9:
        return
    if config.ON_SHORT == "continue":
        print(f"  ⚠️ [{label}] 数据不足（{got}/{want}），按 --on-short continue 用现有数据继续", file=sys.stderr)
        return
    if config.ON_SHORT == "abort":
        print(f"  ⛔ [{label}] 数据不足（{got}/{want}），按 --on-short abort 中止。缓存已落盘，重跑自动断点续传。", file=sys.stderr)
        sys.exit(2)
    print(f"\n  ⚠️ [{label}] 数据不完整：{got}/{want} 条（限流中断或对方微博量本身不足）", file=sys.stderr)
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


def unpin(posts, label):
    """剔除置顶微博（biz 接口可能把置顶老微博排最前，循环剔除）"""
    while len(posts) >= 5:
        t0 = parse_time(posts[0].get("created_at", ""))
        t1 = parse_time(posts[1].get("created_at", ""))
        if not (t0 and t1) or (t1 - t0).days <= 30:
            break
        pinned = posts.pop(0)
        print(f"⚠️ [{label}] 已剔除置顶微博（{pinned.get('created_at','')}）", file=sys.stderr)
    return posts


def load_cache(path, need):
    """读缓存：达到目标的 90% 返回数据，否则返回 None（调用方决定续传或重拉）"""
    if os.path.exists(path):
        try:
            d = json.load(open(path))
            if len(d) >= int(need * 0.9):
                return d
        except Exception:
            pass
    return None
