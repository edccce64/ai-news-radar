"""把 docs/preview.json 渲染成 docs/preview.html（还原飞书卡片样式）。

用法：
    python tools/render_preview.py

preview.json 由真实推送数据 + 真实 LLM 加工生成，见 CHANGELOG。
"""

import html
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "preview.json")
DST = os.path.join(ROOT, "docs", "preview.html")

CSS = """
* { box-sizing: border-box; }
body {
  margin: 0; padding: 28px;
  background: #f5f6f7;
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", "PingFang SC",
               "Segoe UI Emoji", "Segoe UI Symbol", sans-serif;
}
.chat { max-width: 760px; margin: 0 auto; }
.card { background: #fff; border-radius: 8px; overflow: hidden;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.card-head { background: #3370ff; color: #fff; padding: 14px 18px;
             font-size: 16px; font-weight: 600; }
.card-body { padding: 12px; }
.section { font-weight: 600; font-size: 14px; margin: 4px 2px 10px; color: #1f2329; }
.panel { border: 1px solid #dee0e3; border-radius: 5px; margin-bottom: 10px; overflow: hidden; }
.gap { height: 14px; }
.panel-head { display: flex; align-items: center; gap: 8px; padding: 9px 12px; font-size: 14px;
              font-weight: 500; color: #1f2329; background: #fff; }
.panel-head .caret { margin-left: auto; color: #8f959e; font-size: 11px; }
.panel-body { padding: 2px 12px 12px; font-size: 14px; line-height: 1.7; color: #1f2329; }
.panel-body p { margin: 8px 0; }
.panel-body strong { font-weight: 600; }
.panel-body a { color: #3370ff; text-decoration: none; word-break: break-all; }
.stars { color: #f5a623; letter-spacing: 1px; }
.meta { color: #8f959e; font-weight: 400; }
"""

MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
MD_LINK = re.compile(r"\[(.+?)\]\((.+?)\)")


def md(text):
    """把 lark_md 的粗体与链接转成 HTML（只处理这两个标签，够用）。"""
    out = html.escape(text)
    out = MD_BOLD.sub(r"<strong>\1</strong>", out)
    out = MD_LINK.sub(r'<a href="\2" target="_blank">\1</a>', out)
    return out


def main():
    with open(SRC, encoding="utf-8") as f:
        data = json.load(f)

    # preview.json 可以存单卡（{"msg_type", "card"}）或多卡（{"cards": [...]}）
    if "cards" in data:
        cards = [c.get("card", c) for c in data["cards"]]
    else:
        raw = data["card"]
        cards = [raw.get("card", raw)]

    rendered = "".join(_render_card(c) for c in cards)
    title = cards[0].get("header", {}).get("title", {}).get("content", "")
    page = (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
        f'<div class="chat">{rendered}</div></body></html>'
    )
    with open(DST, "w", encoding="utf-8") as f:
        f.write(page)
    print("已生成", DST, f"（{len(cards)} 张卡）")


def _render_card(card) -> str:
    """渲染一张卡片。每个面板只展开第一个，展示展开与折叠两种状态。"""
    blocks = []
    seen_panel = False
    for el in card["body"]["elements"]:
        if el.get("tag") == "markdown":
            blocks.append(f'<div class="section">{md(el["content"])}</div>')
            continue
        header = el.get("header", {})
        title = header.get("title", {}).get("content", "")
        stars, _, rest = title.partition(" ")
        t, _, src = rest.rpartition("（")
        body = el.get("elements", [{}])[0].get("content", "")
        paras = "".join(f"<p>{md(p)}</p>" for p in body.split("\n\n") if p.strip())
        open_ = not seen_panel
        seen_panel = True
        blocks.append(
            f'<div class="panel"><div class="panel-head">'
            f'<span class="stars">{html.escape(stars)}</span>'
            f"<span>{html.escape(t.strip())} "
            f'<span class="meta">（{html.escape(src.strip("（）"))}）</span></span>'
            f'<span class="caret">{"▾" if open_ else "▸"}</span></div>'
            + (f'<div class="panel-body">{paras}</div>' if open_ else "")
            + "</div>"
        )

    card_title = card.get("header", {}).get("title", {}).get("content", "")
    return (
        '<div class="card">'
        f'<div class="card-head">{html.escape(card_title)}</div>'
        f'<div class="card-body">{"".join(blocks)}</div>'
        '</div><div class="gap"></div>'
    )


if __name__ == "__main__":
    main()
