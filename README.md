# 微博配对

> 你的微博暴露了怎样的你？你和 TA 在数据里合拍吗？

基于微博公开数据的关系分析工具——两个入口，五套视觉输出。

- 🔮 **自画像**（免费）：七维面相 + 荒诞判词 → 面相诊断书 / 星空罗盘
- 💑 **双人配对**（需 CLI 套餐）：八维匹配 + 缘分指数 → 情侣 · 朋友 · 商务三种方向

## 快速开始

```bash
# 自画像（免费，weibo-skill 即可）
python3 scripts/self-portrait.py

# 双人配对（需 weibo-cli + Token）
python3 scripts/pair.py --other-uid <对方UID> --my-uid <我方UID>
```

详细说明见 **[用户指南](USER-GUIDE.md)**。

## 依赖

| 工具 | 用途 |
|------|------|
| [weibo-skill](https://github.com/alchaincyf/weibo-skill) | 自画像 + 我方免费数据（向 @微博龙虾助手 私信"连接龙虾"获取凭证） |
| [weibo-cli](https://open.weibo.com/cli) | 配对对方数据（`npm i -g @weibo-ai/weibo-cli`，¥29/月起） |

## 设计

全部 HTML 输出模板的设计方向来自 [花叔设计 Skill（huashu-design）](https://github.com/alchaincyf/huashu-design)。

## 授权

MIT License · 详见 [LICENSE](LICENSE)
