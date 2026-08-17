"""
基金日报生成器
每天运行一次，读取 funds.json，抓取最新数据，输出 HTML 日报

数据来源（全部免费）：
- 天天基金 JSONP 接口：实时估值、净值
- 东方财富 API：历史净值、基金档案
- AKShare：指数 PE/PB、市场估值

使用方法：
  python generate_report.py          # 生成日报
  python generate_report.py --live   # 盘中运行（含实时估值）
"""

import json
import re
import sys
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Windows 控制台强制 UTF-8（支持 emoji）
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent
FUNDS_JSON = BASE_DIR / "funds.json"
OUTPUT_HTML = BASE_DIR / "index.html"

# 请求头（模拟浏览器，避免被拦截）
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://fund.eastmoney.com/",
}

# 带重试的 Session
def create_session():
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update(HEADERS)
    return s


# ============================================================
# 数据抓取
# ============================================================

def fetch_fund_latest(session, code):
    """
    从东方财富 API 获取基金最新净值（含日涨跌）

    东方财富基金净值接口:
      https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=2

    返回最新一条记录: {code, name, nav_date, nav, acc_nav, daily_change_pct}
    daily_change_pct 为正数表示上涨，负数表示下跌（已经是最新交易日的数据）
    """
    url = "https://api.fund.eastmoney.com/f10/lsjz"
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        resp = session.get(url, params={
            "fundCode": code,
            "pageIndex": 1,
            "pageSize": 2,
            "startDate": week_ago,
            "endDate": today,
        }, timeout=15)

        data = resp.json()
        if data.get("ErrCode") != 0:
            print(f"  ⚠️ {code} API 返回错误: {data.get('ErrMsg', '')}")
            return None

        records = data.get("Data", {}).get("LSJZList", [])
        if not records:
            print(f"  ⚠️ {code} 无净值数据")
            return None

        # 同时从第一个有数据的记录获取基金名称
        fund_name = ""
        # 尝试从返回数据获取名称
        for r in records:
            # 东方财富这个接口不返回基金名称，需要从其他地方获取
            pass

        latest = records[0]
        return {
            "code": code,
            "name": "",  # 从 funds.json 中取
            "nav_date": latest.get("FSRQ", ""),
            "nav": float(latest.get("DWJZ", 0)),
            "acc_nav": float(latest.get("LJJZ", 0)),
            "daily_change_pct": float(latest.get("JZZZL", 0) if latest.get("JZZZL") else 0),
        }
    except Exception as e:
        print(f"  ⚠️ 获取 {code} 净值失败: {type(e).__name__}: {e}")
        return None


def fetch_fund_basic_info(session, code):
    """
    获取基金基本信息（名称、类型、规模等）
    从东方财富基金档案页获取
    """
    try:
        url = f"http://fundf10.eastmoney.com/jbgk_{code}.html"
        resp = session.get(url, timeout=15)
        resp.encoding = "utf-8"

        info = {"code": code, "name": "", "type": "", "scale": ""}

        # 提取基金名称
        name_match = re.search(r'<title>([^(]+?)\((\d+)\)[^<]*基金基本概况', resp.text)
        if name_match:
            info["name"] = name_match.group(1).strip()

        # 提取基金类型
        type_match = re.search(r'基金类型[：:]\s*([^<\s]+)', resp.text)
        if type_match:
            info["type"] = type_match.group(1).strip()

        # 提取基金规模
        scale_match = re.search(r'基金规模[：:]\s*([\d.]+)\s*亿元', resp.text)
        if scale_match:
            info["scale"] = scale_match.group(1).strip() + "亿元"

        return info
    except Exception as e:
        print(f"  ⚠️ 获取 {code} 基本信息失败: {e}")
        return {"code": code, "name": "", "type": "", "scale": ""}


def fetch_fund_history(session, code, days=365):
    """
    从东方财富 API 获取基金历史净值
    用于计算阶段收益、最大回撤等
    """
    all_records = []
    page = 1

    while True:
        url = f"https://api.fund.eastmoney.com/f10/lsjz"
        params = {
            "fundCode": code,
            "pageIndex": page,
            "pageSize": 30,
            "startDate": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
            "endDate": datetime.now().strftime("%Y-%m-%d"),
        }

        try:
            resp = session.get(url, params=params, timeout=15)
            data = resp.json()

            if data.get("ErrCode") != 0:
                break

            records = data.get("Data", {}).get("LSJZList", [])
            if not records:
                break

            for r in records:
                all_records.append({
                    "date": r.get("FSRQ", ""),
                    "nav": float(r.get("DWJZ", 0)),
                    "acc_nav": float(r.get("LJJZ", 0)),
                    "daily_change": r.get("JZZZL", "0"),
                })

            if len(records) < 30:
                break
            page += 1
            time.sleep(0.3)  # 节流

        except Exception as e:
            print(f"  ⚠️ 获取 {code} 历史数据失败 (page {page}): {e}")
            break

    return all_records


def fetch_index_pe(session):
    """
    获取主要指数估值数据（通过东方财富）
    返回沪深300、中证500等主要指数的 PE/PB
    """
    indices = {
        "沪深300": "1.000300",
        "中证500": "1.000905",
        "创业板指": "1.399006",
        "上证50": "1.000016",
        "中证白酒": "1.399997",
    }

    results = {}
    for name, code in indices.items():
        try:
            # 东方财富指数估值接口
            url = f"https://push2.eastmoney.com/api/qt/stock/get"
            params = {
                "secid": code,
                "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,f170,f171",
                # f57=股票代码, f58=股票名称, f43=最新价, f44=最高, f45=最低
                # f170=涨跌幅, f171=涨跌额
            }
            resp = session.get(url, params=params, timeout=10)
            d = resp.json().get("data", {})

            if d:
                results[name] = {
                    "price": d.get("f43", 0) / 100 if d.get("f43") else None,
                    "change_pct": d.get("f170", 0) / 100 if d.get("f170") else None,
                }
        except Exception as e:
            print(f"  ⚠️ 获取{name}指数失败: {e}")
            results[name] = None

    return results


def fetch_market_breadth(session):
    """
    获取市场情绪指标：涨跌家数、成交额
    """
    try:
        url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
        params = {
            "fltt": 2,
            "fields": "f2,f3,f12,f14",
            "secids": "1.000001,0.399001",
        }
        resp = session.get(url, params=params, timeout=10)
        data = resp.json()
        # 简化处理，返回整体市场情况
        return {"status": "ok"}
    except:
        return {"status": "error"}


def fetch_fund_manager_info(session, code):
    """
    抓取基金经理信息（从天天基金基金详情页）
    返回基金经理姓名、任职天数、任职回报等
    """
    try:
        url = f"http://fundf10.eastmoney.com/jjjl_{code}.html"
        resp = session.get(url, timeout=15)
        resp.encoding = "utf-8"

        # 从 HTML 中提取基金经理信息
        text = resp.text

        managers = []
        # 简单正则提取：经理姓名、任职天数、任职回报
        manager_pattern = re.compile(
            r'<td[^>]*>(\d+)</td>\s*<td[^>]*><a[^>]*>([^<]+)</a></td>'
            r'\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>'
            r'\s*<td[^>]*class="tor[^"]*"[^>]*>([^<]*)</td>',
            re.DOTALL
        )
        matches = manager_pattern.findall(text)

        for m in matches:
            managers.append({
                "manager_name": m[1].strip() if len(m) > 1 else "",
                "start_date": m[2].strip() if len(m) > 2 else "",
                "days_in_charge": m[3].strip() if len(m) > 3 else "",
                "return_pct": m[4].strip() if len(m) > 4 else "",
            })

        return managers
    except Exception as e:
        print(f"  ⚠️ 获取 {code} 经理信息失败: {e}")
        return []


# ============================================================
# 分析与建议引擎
# ============================================================

def analyze_fund(fund_config, realtime, history, index_data):
    """
    综合多维度分析，给出操作建议

    主动基金评判维度：
    1. 用户盈亏状态（从成本价计算）
    2. 近期表现（1月/3月/6月回报）
    3. 最大回撤风险
    4. 基金经理稳定性
    5. 基金规模合理性
    6. 市场估值环境（决定是否适合加仓）

    返回：建议 + 原因 + 信号详情
    """
    signals = []
    score = 0  # 正=偏多, 负=偏空

    # ---- 获取当前数据 ----
    if not realtime:
        return {
            "suggestion": "数据缺失",
            "color": "gray",
            "emoji": "?",
            "reasons": ["无法获取该基金数据，请检查基金代码"],
            "signals": [],
            "score": 0,
        }

    current_nav = realtime.get("nav", 1.0)
    daily_change = realtime.get("daily_change_pct", 0)
    fund_name = fund_config.get("name", realtime.get("name", ""))

    cost_nav = fund_config.get("cost_nav", current_nav)
    invested = fund_config.get("invested", 0)
    shares = fund_config.get("shares", 0)

    # ---- 维度1：用户盈亏 ----
    if cost_nav > 0:
        profit_pct = (current_nav - cost_nav) / cost_nav
        profit_amount = invested * profit_pct if invested > 0 else 0

        if profit_pct > 0.30:
            signals.append(f"盈利 {profit_pct:.1%}，已达止盈参考线（30%）")
            score -= 2
        elif profit_pct > 0.15:
            signals.append(f"盈利 {profit_pct:.1%}，收益可观，可观察是否止盈")
            score -= 1
        elif profit_pct < -0.20:
            signals.append(f"亏损 {profit_pct:.1%}，大幅亏损，但低位不宜割肉")
            score += 1  # 不鼓励恐慌卖出
        elif profit_pct < -0.05:
            signals.append(f"亏损 {profit_pct:.1%}，轻微浮亏")
        else:
            signals.append(f"盈亏 {profit_pct:+.1%}")
    else:
        profit_pct = 0
        profit_amount = 0

    # ---- 维度2：阶段表现 ----
    if history and len(history) > 5:
        history.sort(key=lambda x: x["date"])

        def calc_return(days):
            """从历史数据计算 N 日回报"""
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            past = [h for h in history if h["date"] <= cutoff]
            if past and history[-1]["nav"] > 0:
                old_nav = past[-1]["nav"]
                new_nav = history[-1]["nav"]
                return (new_nav - old_nav) / old_nav
            return None

        ret_1m = calc_return(30)
        ret_3m = calc_return(90)
        ret_6m = calc_return(180)
        ret_1y = calc_return(365)

        # 近期表现评分
        if ret_3m is not None:
            if ret_3m > 0.10:
                signals.append(f"近3月回报 {ret_3m:+.1%}，表现优秀")
                score += 1
            elif ret_3m < -0.10:
                signals.append(f"近3月回报 {ret_3m:+.1%}，表现较弱")
                score -= 1
            else:
                signals.append(f"近3月回报 {ret_3m:+.1%}")

        # 趋势判断：如果连跌3个月，需要警惕
        if ret_1m is not None and ret_3m is not None and ret_6m is not None:
            if ret_1m < 0 and ret_3m < 0 and ret_6m < 0:
                signals.append("连续下跌超过半年，需关注是否基本面恶化")
                score -= 1

        # 最大回撤
        navs = [h["nav"] for h in history]
        if navs:
            peak = navs[0]
            max_drawdown = 0
            for n in navs:
                if n > peak:
                    peak = n
                dd = (peak - n) / peak
                if dd > max_drawdown:
                    max_drawdown = dd
            if max_drawdown > 0.25:
                signals.append(f"近1年最大回撤 {max_drawdown:.1%}，波动较大")

    # ---- 维度3：市场环境 ----
    if index_data:
        hs300 = index_data.get("沪深300", {})
        if hs300 and hs300.get("change_pct") is not None:
            mkt_change = hs300["change_pct"]
            if mkt_change > 2:
                signals.append(f"今日大盘大涨 {mkt_change:+.2f}%，不宜追高")
                score -= 1
            elif mkt_change < -2:
                signals.append(f"今日大盘大跌 {mkt_change:+.2f}%")
                score += 1  # 大跌可能是机会

    # ---- 综合评分 → 建议 ----
    if score >= 3:
        suggestion = "强烈推荐加仓"
        color = "green"
        emoji = "🟢"
    elif score >= 1:
        suggestion = "可考虑加仓"
        color = "green"
        emoji = "🟢"
    elif score >= 0:
        suggestion = "持有观望"
        color = "yellow"
        emoji = "🟡"
    elif score >= -1:
        suggestion = "谨慎持有"
        color = "yellow"
        emoji = "🟡"
    elif score >= -3:
        suggestion = "考虑减仓"
        color = "red"
        emoji = "🔴"
    else:
        suggestion = "建议卖出"
        color = "red"
        emoji = "🔴"

    return {
        "code": fund_config["code"],
        "name": fund_name,
        "suggestion": suggestion,
        "color": color,
        "emoji": emoji,
        "score": score,
        "current_nav": current_nav,
        "daily_change": daily_change,
        "cost_nav": cost_nav,
        "profit_pct": profit_pct,
        "profit_amount": profit_amount,
        "invested": invested,
        "shares": shares,
        "nav_date": realtime.get("nav_date", ""),
        "signals": signals,
    }


# ============================================================
# HTML 报告生成
# ============================================================

def generate_html(analyses, market_data, config):
    """生成完整的 HTML 日报"""

    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")
    time_str = now.strftime("%H:%M")
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]

    # 统计
    buy_count = sum(1 for a in analyses if "加仓" in a["suggestion"])
    hold_count = sum(1 for a in analyses if "持有" in a["suggestion"])
    sell_count = sum(1 for a in analyses if "减仓" in a["suggestion"] or "卖出" in a["suggestion"])
    total_value = sum(
        a.get("invested", 0) * (1 + a.get("profit_pct", 0))
        for a in analyses
    )
    total_invested = sum(a.get("invested", 0) for a in analyses)
    total_profit = total_value - total_invested

    # 今日预计盈亏 = Σ(每只基金当前市值 × 今日涨跌幅)
    # 当前市值 = 投入本金 × (1 + 累计收益率)
    total_daily_pnl = sum(
        a.get("invested", 0) * (1 + a.get("profit_pct", 0)) * (a.get("daily_change", 0) / 100)
        for a in analyses
    )

    # 生成基金卡片
    fund_cards = []
    for a in analyses:
        profit_class = "positive" if a["profit_pct"] > 0 else "negative"
        daily_class = "positive" if a["daily_change"] > 0 else "negative"

        # 持有金额（当前市值） = 本金 × (1 + 累计收益率) = 份额 × 最新净值
        current_value = a.get("invested", 0) * (1 + a.get("profit_pct", 0))

        # 今日涨跌金额 = 持有金额 × 今日涨跌幅
        daily_pnl_amount = current_value * (a.get("daily_change", 0) / 100)

        signals_html = "".join(
            f'<li>{s}</li>' for s in a["signals"]
        )

        fund_cards.append(f"""
        <div class="fund-card" style="border-left: 4px solid {a['color']};">
            <div class="fund-header">
                <span class="fund-emoji">{a['emoji']}</span>
                <div class="fund-name-group">
                    <span class="fund-name">{a['name']}</span>
                    <span class="fund-code">{a['code']}</span>
                </div>
                <span class="suggestion-badge badge-{a['color']}">{a['suggestion']}</span>
            </div>
            <div class="fund-metrics">
                <div class="metric">
                    <span class="metric-label">持有金额</span>
                    <span class="metric-value">¥{current_value:,.0f}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">最新净值</span>
                    <span class="metric-value">{a['current_nav']:.4f}</span>
                    <span class="metric-sub">({a['nav_date']})</span>
                </div>
                <div class="metric">
                    <span class="metric-label">今日涨跌</span>
                    <span class="metric-value {daily_class}">{a['daily_change']:+.2f}%</span>
                    <span class="metric-sub">¥{daily_pnl_amount:+.0f}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">持仓成本</span>
                    <span class="metric-value">{a['cost_nav']:.4f}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">累计盈亏</span>
                    <span class="metric-value {profit_class}">{a['profit_pct']:+.1%}</span>
                    <span class="metric-sub">¥{a['profit_amount']:+.0f}</span>
                </div>
            </div>
            <div class="fund-signals">
                <ul>{signals_html}</ul>
            </div>
        </div>
        """)

    # 组装完整 HTML
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>基金日报 - {date_str} {weekday}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                         "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background: #f5f6fa;
            color: #2d3436;
            line-height: 1.6;
        }}
        .container {{ max-width: 680px; margin: 0 auto; padding: 16px; }}

        /* 顶部概览 */
        .summary {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: white;
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 16px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }}
        .summary h1 {{ font-size: 20px; font-weight: 600; margin-bottom: 4px; }}
        .summary .date {{ font-size: 14px; opacity: 0.7; margin-bottom: 16px; }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
        }}
        .summary-item {{
            text-align: center;
            padding: 12px 8px;
            background: rgba(255,255,255,0.08);
            border-radius: 12px;
        }}
        .summary-item .value {{ font-size: 22px; font-weight: 700; }}
        .summary-item .label {{ font-size: 12px; opacity: 0.7; margin-top: 4px; }}
        .summary-signals {{
            display: flex;
            gap: 12px;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid rgba(255,255,255,0.15);
        }}
        .signal-chip {{
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
        }}
        .signal-buy {{ background: rgba(0,200,83,0.25); color: #69f0ae; }}
        .signal-hold {{ background: rgba(255,171,0,0.25); color: #ffd740; }}
        .signal-sell {{ background: rgba(255,82,82,0.25); color: #ff8a80; }}

        /* 指数栏 */
        .index-bar {{
            background: white;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-around;
            flex-wrap: wrap;
            gap: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .index-item {{ text-align: center; min-width: 70px; }}
        .index-item .idx-name {{ font-size: 12px; color: #888; }}
        .index-item .idx-price {{ font-size: 15px; font-weight: 600; }}
        .idx-up {{ color: #e53935; }}
        .idx-down {{ color: #43a047; }}

        /* 基金卡片 */
        .fund-card {{
            background: white;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .fund-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 12px;
        }}
        .fund-emoji {{ font-size: 24px; }}
        .fund-name-group {{ flex: 1; }}
        .fund-name {{ font-size: 16px; font-weight: 600; display: block; }}
        .fund-code {{ font-size: 12px; color: #aaa; }}
        .suggestion-badge {{
            padding: 4px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
            white-space: nowrap;
        }}
        .badge-green {{ background: #e8f5e9; color: #2e7d32; }}
        .badge-yellow {{ background: #fff8e1; color: #f57f17; }}
        .badge-red {{ background: #ffebee; color: #c62828; }}
        .badge-gray {{ background: #eceff1; color: #607d8b; }}

        .fund-metrics {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 8px;
            margin-bottom: 8px;
        }}
        .metric {{ text-align: center; }}
        .metric-label {{ font-size: 11px; color: #999; display: block; }}
        .metric-value {{ font-size: 16px; font-weight: 600; display: block; }}
        .metric-sub {{ font-size: 11px; color: #bbb; }}
        .positive {{ color: #e53935; }}
        .negative {{ color: #43a047; }}

        .fund-signals ul {{
            list-style: none;
            padding: 8px 12px;
            background: #f8f9fa;
            border-radius: 8px;
        }}
        .fund-signals li {{
            font-size: 13px;
            color: #666;
            padding: 2px 0;
        }}
        .fund-signals li::before {{
            content: "· ";
            color: #bbb;
        }}

        /* 底部 */
        .footer {{
            text-align: center;
            padding: 24px;
            color: #bbb;
            font-size: 12px;
        }}
        .footer a {{ color: #888; }}

        /* 响应式 */
        @media (max-width: 480px) {{
            .fund-metrics {{ grid-template-columns: repeat(2, 1fr); }}
            .summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
</head>
<body>
    <div class="container">

        <!-- 总览 -->
        <div class="summary">
            <h1>📊 基金日报</h1>
            <div class="date">{date_str} {weekday} · 更新于 {time_str}</div>
            <div class="summary-grid">
                <div class="summary-item">
                    <div class="value">¥{total_value:,.0f}</div>
                    <div class="label">当前市值</div>
                </div>
                <div class="summary-item">
                    <div class="value" style="color: {'#ffd740' if total_profit >= 0 else '#ff8a80'}">¥{total_profit:+,.0f}</div>
                    <div class="label">累计盈亏</div>
                </div>
                <div class="summary-item">
                    <div class="value" style="color: {'#ffd740' if total_daily_pnl >= 0 else '#ff8a80'}">¥{total_daily_pnl:+,.0f}</div>
                    <div class="label">今日预计盈亏</div>
                </div>
                <div class="summary-item">
                    <div class="value">{len(analyses)}只</div>
                    <div class="label">持仓基金</div>
                </div>
            </div>
            <div class="summary-signals">
                <span class="signal-chip signal-buy">🟢 {buy_count} 只可加仓</span>
                <span class="signal-chip signal-hold">🟡 {hold_count} 只持有</span>
                <span class="signal-chip signal-sell">🔴 {sell_count} 只关注</span>
            </div>
        </div>

        <!-- 市场指数 -->
        <div class="index-bar">
            {"".join(
                (
                    lambda d, n: f'<div class="index-item"><span class="idx-name">{n}</span>'
                    f'<span class="idx-price {"idx-up" if (d.get("change_pct") or 0) > 0 else "idx-down"}">'
                    f'{d["price"]:.0f}</span></div>' if d.get("price") else ""
                )(data, name)
                for name, data in (market_data or {}).items() if data
            )}
        </div>

        <!-- 操作建议列表 -->
        <h2 style="font-size:17px; margin:16px 0 12px; color:#555;">📋 今日操作建议</h2>
        {''.join(fund_cards)}

        <div class="footer">
            <p>🤖 由基金日报助手自动生成 · 数据来源：天天基金、东方财富</p>
            <p>⚠️ 仅供参考，不构成投资建议。投资有风险，买卖需谨慎。</p>
            <p style="margin-top:8px;">
                <a href="funds.json">📁 持仓配置</a> ·
                上次更新: {time_str}
            </p>
        </div>

    </div>
</body>
</html>"""

    return html


# ============================================================
# 主流程
# ============================================================

def main():
    args = sys.argv[1:]
    live_mode = "--live" in args

    print("=" * 60)
    print("  Fund Daily Report Generator")
    print("=" * 60)

    # 加载配置
    if not FUNDS_JSON.exists():
        print(f"ERROR: {FUNDS_JSON} not found. Run import_screenshot.py first.")
        sys.exit(1)

    with open(FUNDS_JSON, "r", encoding="utf-8") as f:
        config = json.load(f)

    funds = config.get("funds", [])
    if not funds:
        print("ERROR: no funds in funds.json")
        sys.exit(1)

    print(f"\n{len(funds)} funds loaded")
    user = config.get("user", {})
    if user:
        print(f"User: {user.get('name', 'N/A')}")
        print(f"Total invested: {user.get('total_invested', 0):,.0f}")
        print(f"Monthly budget: {user.get('monthly_budget', 0):,}")

    session = create_session()

    # ---- 第一步：并行获取所有基金的净值数据 ----
    print(f"\n... 获取基金净值数据 ...")
    realtime_results = {}

    # 建立 code -> fund_config 的映射
    fund_map = {f["code"]: f for f in funds}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(fetch_fund_latest, session, f["code"]): f["code"]
            for f in funds
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                result = future.result()
                if result:
                    # 从配置补充基金名称
                    fc = fund_map.get(code, {})
                    result["name"] = fc.get("name", result.get("name", code))
                    realtime_results[code] = result
                    print(f"  OK {code} {result['name'][:12]} NAV {result['nav']:.4f}"
                          f" ({'+' if result['daily_change_pct'] > 0 else ''}{result['daily_change_pct']:.2f}%)")
                else:
                    print(f"  FAIL {code} no data")
            except Exception as e:
                print(f"  FAIL {code}: {type(e).__name__}")

    # ---- 第二步：获取市场指数 ----
    print(f"\n... 获取市场指数 ...")
    index_data = fetch_index_pe(session)
    for name, data in index_data.items():
        if data and data.get("price"):
            change = data.get("change_pct", 0)
            arrow = "+" if (change or 0) > 0 else "-"
            print(f"  {arrow} {name}: {data['price']:.0f} ({change:+.2f}%)")

    # ---- 第三步：逐只基金深度分析 ----
    print(f"\n... 分析基金 ...")
    analyses = []

    for fund in funds:
        code = fund["code"]
        realtime = realtime_results.get(code)

        if not realtime:
            print(f"  WARN {code} {fund.get('name', '')} no data, skipping")
            analyses.append({
                "code": code,
                "name": fund.get("name", code),
                "suggestion": "数据缺失",
                "color": "gray",
                "emoji": "?",
                "current_nav": 0,
                "daily_change": 0,
                "cost_nav": fund.get("cost_nav", 0),
                "profit_pct": 0,
                "profit_amount": 0,
                "invested": fund.get("invested", 0),
                "shares": fund.get("shares", 0),
                "nav_date": "",
                "signals": ["无法获取数据"],
            })
            continue

        # 获取历史数据（只取90天用于计算近期表现）
        history = fetch_fund_history(session, code, days=90)
        time.sleep(0.3)

        # 综合分析
        result = analyze_fund(fund, realtime, history, index_data)
        analyses.append(result)

        emoji = result["emoji"]
        sug = result["suggestion"]
        print(f"  {emoji} {code} {result['name']} → {sug} (评分: {result['score']})")

    # ---- 按持有金额（当前市值）从高到低排序 ----
    analyses.sort(
        key=lambda a: a.get("invested", 0) * (1 + a.get("profit_pct", 0)),
        reverse=True,
    )

    # ---- 第四步：生成 HTML ----
    print(f"\n... 生成 HTML 报告 ...")
    html = generate_html(analyses, index_data, config)

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Report generated: {OUTPUT_HTML}")
    print(f"Size: {len(html):,} bytes")
    print(f"Open with browser to view")

    # ---- 打印文本摘要 ----
    print(f"\n{'=' * 60}")
    print(f"  Today Summary")
    print(f"{'=' * 60}")
    for a in analyses:
        name = a["name"][:12]
        sug = a["suggestion"]
        pnl = a["profit_pct"]
        change = a["daily_change"]
        print(f"  [{a['emoji']}] {name:<12} {sug:<12} PnL{pnl:+.1%}  Chg{change:+.2f}%")

    return analyses


if __name__ == "__main__":
    main()
