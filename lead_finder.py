# -*- coding: utf-8 -*-
"""
客户线索自动收集与打分工具  lead_finder.py
零第三方依赖，仅使用 Python 标准库。

功能：
  1. 读取多渠道线索原始表（企业名录/展会名片/平台导出，字段一致即可）
  2. 手机号标准化清洗 + 按号码哈希去重（同号码不同格式只保留信息最全的一条）
  3. 按城市 / 行业关键词筛选
  4. 线索评分：联系方式完整度、决策人线索、来源质量、需求关键词
  5. 导出排序后的线索表，输出收集漏斗统计

用法：
  python lead_finder.py --city 成都 --industry 广告
  python lead_finder.py --city 西安
  python lead_finder.py                      # 不过滤，处理全部
  python lead_finder.py --input demo_sources.csv --output leads_ranked.csv

接入真实数据源：
  把企业信息平台/黄页导出的 CSV 放在同目录、保持表头一致即可；
  也可用 fetch_page() 抓取公开列表页 HTML 后用正则提取（见文件末尾示例）。
注意：仅可采集公开发布的企业商务联系信息，遵守目标网站robots与使用条款。
"""
import csv, re, sys, argparse, hashlib
from collections import Counter

HEADERS = ["公司名","联系人","电话","城市","行业","来源","备注"]
SOURCE_WEIGHT = {"朋友转介绍": 25, "展会名片": 20, "行业沙龙": 18, "软博会": 18,
                 "游戏展会": 18, "抖音私信": 15, "地推扫码": 12, "企查查导出": 12,
                 "企业名录": 10, "大众点评导出": 8, "美团导出": 8, "1688导出": 8,
                 "懂车帝导出": 8, "新氧导出": 8, "携程导出": 8, "贝壳导出": 8,
                 "阿里国际站": 10, "公众号留言": 8, "行业名录": 5}
DECISION_TITLES = ["总","经理","院长","厂长","总监","顾问","工"]
DEMAND_KEYWORDS = ["投放","推广","获客","扩招","开业","GMV","年销","加盟","分销","年框","线索"]


def norm_phone(raw):
    """提取手机号(11位)或区号座机；返回标准号码，无有效号码返回空串"""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    m = re.search(r"1[3-9]\d{9}$", digits)          # 手机号（含86前缀）
    if m:
        return m.group()
    m2 = re.search(r"(0\d{2,3}\d{7,8})$", digits)    # 座机
    if m2:
        return m2.group()
    return ""


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return [dict(r) for r in csv.DictReader(f)]


def score_lead(row):
    s = 0
    phone = row["电话"]
    if phone.startswith("1"):      # 手机直联 +20，座机总机 +8
        s += 20
    elif phone:
        s += 8
    name = row["联系人"]
    if name and any(t in name for t in DECISION_TITLES):
        s += 20
    elif name:
        s += 8
    s += SOURCE_WEIGHT.get(row["来源"], 5)
    note = row["备注"] or ""
    hits = [k for k in DEMAND_KEYWORDS if k in note]
    s += min(len(hits) * 8, 24)
    if len(row["公司名"]) >= 8:    # 全称完整度
        s += 4
    return min(s, 100), hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="demo_sources.csv")
    ap.add_argument("--output", default="leads_ranked.csv")
    ap.add_argument("--city", default="")
    ap.add_argument("--industry", default="")
    args = ap.parse_args()

    raw = load(args.input)
    n_raw = len(raw)

    # 1) 清洗 + 去重（同号码保留信息完整度高的）
    pool = {}
    for r in raw:
        phone = norm_phone(r["电话"])
        r["电话"] = phone
        key = phone or ("无号码:" + r["公司名"])
        completeness = sum(1 for v in r.values() if v)
        if key not in pool or completeness > pool[key][0]:
            pool[key] = (completeness, r)
    cleaned = [v[1] for v in pool.values()]
    n_dedup = n_raw - len(cleaned)

    # 2) 过滤
    city, ind = args.city.strip(), args.industry.strip()
    flt = [r for r in cleaned
           if (not city or city in r["城市"])
           and (not ind or ind in r["行业"])]

    # 3) 打分排序
    scored = []
    for r in flt:
        sc, hits = score_lead(r)
        r["评分"], r["需求命中"] = sc, "/".join(hits)
        scored.append(r)
    scored.sort(key=lambda r: r["评分"], reverse=True)

    # 4) 导出
    out_head = HEADERS + ["评分","需求命中"]
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=out_head)
        w.writeheader()
        for r in scored:
            w.writerow({k: r.get(k, "") for k in out_head})

    # 5) 漏斗 + 来源分布
    valid_phone = sum(1 for r in cleaned if r["电话"])
    print("=" * 52)
    print("             客户线索收集漏斗")
    print("=" * 52)
    print(f"  原始线索            {n_raw} 条")
    print(f"  去重剔除            {n_dedup} 条（同号不同格式/重复录入）")
    print(f"  有效联系方式        {valid_phone} 条（手机/座机）")
    print(f"  条件筛选后          {len(scored)} 条"
          f"{'  [城市=' + city + ']' if city else ''}{'  [行业=' + ind + ']' if ind else ''}")
    print("-" * 52)
    src = Counter(r["来源"] for r in scored)
    print("  来源分布：" + "；".join(f"{k} {v}" for k, v in src.most_common(5)))
    print("-" * 52)
    print(f"  TOP 5 高优线索：")
    for r in scored[:5]:
        title = r["联系人"] or "无联系人"
        print(f"   {r['评分']:>3}分  {r['公司名'][:22]:<24} {title}  {r['电话'] or '无号码'}")
    print("=" * 52)
    print(f"  已导出：{args.output}")


# ---- 真实网页数据源接入示例（默认不执行，需按需开启）----
def fetch_page(url):
    """抓取公开企业列表页，返回HTML文本；正则按目标站点结构调整。"""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    pattern = re.compile(
        r'公司名[^>]*>([^<]{6,30}公司).*?电话[^>]*>(1[3-9]\d{9})', re.S)
    return [{"公司名": a, "联系人": "", "电话": b, "城市": "", "行业": "",
             "来源": "网页采集", "备注": url} for a, b in pattern.findall(html)]


if __name__ == "__main__":
    main()
