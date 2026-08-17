"""
支付宝基金截图识别工具
支持两种方式：
1. 本地 OCR (EasyOCR/PaddleOCR) - 免费、离线
2. 调用 Claude Vision API - 更精准、需要网络和API Key

使用方法：
  python import_screenshot.py screenshot1.png screenshot2.png
  python import_screenshot.py --method claude screenshot.png
  python import_screenshot.py --all  # 识别 screenshots/ 目录下所有图片

输出：更新 funds.json 中的持仓数据
"""

import json
import re
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

# ============================================================
# 配置
# ============================================================
FUNDS_JSON = Path(__file__).parent / "funds.json"
SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"


def load_funds():
    with open(FUNDS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def save_funds(data):
    with open(FUNDS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ 已更新 {FUNDS_JSON}")


# ============================================================
# 方法一：本地 OCR (EasyOCR)
# ============================================================
def ocr_with_easyocr(image_paths):
    """使用 EasyOCR 识别图片中的文字（免费、离线、支持中文）"""
    try:
        import easyocr
    except ImportError:
        print("❌ 请先安装 EasyOCR: pip install easyocr")
        print("   首次运行会自动下载中文模型 (~100MB)，需要几分钟")
        return None

    print("🔍 正在加载 EasyOCR 中文模型...")
    reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)  # GPU=False 适用于 CPU 环境

    all_texts = []
    for img_path in image_paths:
        print(f"  📷 识别: {img_path}")
        results = reader.readtext(str(img_path), detail=0)
        text = "\n".join(results)
        all_texts.append(text)
        print(f"     识别到 {len(results)} 行文字")

    return "\n---PAGE BREAK---\n".join(all_texts)


# ============================================================
# 方法二：PaddleOCR (更精准的中文 OCR)
# ============================================================
def ocr_with_paddleocr(image_paths):
    """使用 PaddleOCR 识别（中文精度更高，但安装稍复杂）"""
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        print("❌ 请先安装 PaddleOCR: pip install paddlepaddle paddleocr")
        return None

    print("🔍 正在加载 PaddleOCR...")
    ocr = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)

    all_texts = []
    for img_path in image_paths:
        print(f"  📷 识别: {img_path}")
        results = ocr.ocr(str(img_path), cls=True)
        if results and results[0]:
            lines = [line[1][0] for line in results[0]]
            text = "\n".join(lines)
            all_texts.append(text)
            print(f"     识别到 {len(lines)} 行文字")

    return "\n---PAGE BREAK---\n".join(all_texts)


# ============================================================
# 方法三：Claude Vision API (最精准)
# ============================================================
def ocr_with_claude(image_paths):
    """使用 Claude Vision API 识别并直接结构化输出

    需要设置环境变量: ANTHROPIC_API_KEY
    pip install anthropic
    """
    try:
        import anthropic
        import base64
    except ImportError:
        print("❌ 请先安装 anthropic: pip install anthropic")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ 请设置环境变量 ANTHROPIC_API_KEY")
        print("   获取 Key: https://console.anthropic.com/")
        return None

    client = anthropic.Anthropic(api_key=api_key)

    # 读取图片并转 base64
    images_content = []
    for img_path in image_paths:
        with open(img_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(img_path)[1].lower()
        media_type = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, "image/png")
        images_content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": img_data}
        })

    print("🤖 正在用 Claude Vision 识别截图...")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                *images_content,
                {
                    "type": "text",
                    "text": """这是支付宝基金持仓页面的截图。请从中提取我的基金持仓信息。

请返回 JSON 格式（只返回 JSON，不要其他文字）：
{
  "funds": [
    {
      "code": "基金代码（6位数字）",
      "name": "基金名称",
      "current_value": 当前持仓金额（数字）,
      "profit_loss": 累计盈亏金额（数字，亏损为负数）,
      "profit_loss_pct": 累计收益率（如 0.05 表示5%，-0.03 表示-3%）
    }
  ],
  "total_value": 总持仓金额,
  "total_profit": 累计总盈亏
}

注意：
- 基金代码是6位纯数字
- 收益率可能显示为百分比，请转为小数（如 5.2% → 0.052）
- 如果图片中有多个页面（滑动截图），请合并去重
- 忽略页面中的广告和推荐内容
- 如果不确定某个字段，填 null"""
                }
            ]
        }]
    )

    # 解析 Claude 的返回
    response_text = message.content[0].text
    # 清理可能包裹的 markdown 代码块
    response_text = re.sub(r'^```(?:json)?\s*', '', response_text.strip())
    response_text = re.sub(r'\s*```$', '', response_text)

    try:
        parsed = json.loads(response_text)
        print(f"✅ Claude 识别到 {len(parsed.get('funds', []))} 只基金")
        return parsed
    except json.JSONDecodeError:
        print("⚠️ Claude 返回格式有问题，原始文本：")
        print(response_text[:500])
        return None


# ============================================================
# 文本解析：从 OCR 结果中提取基金信息
# ============================================================
def parse_ocr_text(raw_text):
    """
    从 OCR 识别的原始文本中提取基金持仓信息
    支持支付宝基金页面的常见格式

    支付宝基金持仓页面常见的字段模式：
    - 基金代码：6位数字（如 005827）
    - 基金名称：中文+数字（如 易方达蓝筹精选混合）
    - 持有金额：¥XXX.XX 或 XXX.XX元
    - 收益：+XXX.XX 或 -XXX.XX，+XX% 或 -XX%
    """
    funds_found = []

    # 按页面分割
    pages = raw_text.split("---PAGE BREAK---")

    for page_text in pages:
        lines = page_text.strip().split("\n")

        # 模式1：支付宝"我的"→"基金"页面格式
        # 通常格式为：基金名称 + 基金代码 + 持有金额 + 收益
        fund_code_pattern = re.compile(r'\b(\d{6})\b')  # 6位基金代码
        money_pattern = re.compile(r'[¥￥]?\s*([\d,]+\.?\d*)\s*(?:元)?')
        pct_pattern = re.compile(r'([+-]?\d+\.?\d*)\s*%')
        profit_pattern = re.compile(r'([+-]?\s*[\d,]+\.?\d*)')

        # 遍历识别到的基金代码
        seen_codes = set()
        for i, line in enumerate(lines):
            code_match = fund_code_pattern.search(line)
            if not code_match:
                continue

            code = code_match.group(1)

            # 过滤掉非基金代码（如日期、金额等）
            if code in seen_codes:
                continue
            # 简单的基金代码范围校验
            if int(code) < 1 or int(code) > 999999:
                continue

            seen_codes.add(code)

            # 尝试提取基金名称（通常在代码附近）
            name = code  # fallback
            for j in range(max(0, i - 2), min(len(lines), i + 3)):
                # 基金名称通常包含中文和"混合"、"精选"、"指数"、"ETF"等词
                candidate = lines[j].strip()
                if any(kw in candidate for kw in ['基金', '混合', '精选', '指数', '成长',
                                                    '创新', '医疗', '消费', '新能源',
                                                    '蓝筹', '军工', '白酒', 'ETF', 'LOF']):
                    # 取中文字符为主的部分
                    name_match = re.search(r'[一-鿿][一-鿿A-Za-z0-9（）()]*(?:混合|精选|指数|成长|创新|医疗|消费|新能源|蓝筹|军工|白酒|ETF|LOF|联接|增强)[A-Za-z]?', candidate)
                    if name_match:
                        name = name_match.group(0)
                        break

            funds_found.append({
                "code": code,
                "name": name,
                "current_value": None,
                "profit_loss": None,
                "profit_loss_pct": None
            })

    return funds_found


def merge_with_existing_config(funds_found, screenshot_data=None):
    """
    将 OCR 识别结果合并到现有的 funds.json 配置中

    规则：
    1. 新识别到的基金 → 添加到列表
    2. 已存在的基金 → 更新持仓数据
    3. 配置中但未识别到的 → 保留（可能是其他平台买的）
    """
    existing = load_funds()
    existing_codes = {f["code"]: f for f in existing["funds"]}

    # 如果 Claude Vision 返回了结构化数据
    if screenshot_data and isinstance(screenshot_data, dict):
        structured_funds = screenshot_data.get("funds", [])
        for sf in structured_funds:
            code = sf.get("code", "")
            if not code:
                continue

            if code in existing_codes:
                # 更新现有基金
                ef = existing_codes[code]
                if sf.get("current_value"):
                    # 反推份额 = 当前市值 / (1 + 收益率) / 当前净值...
                    # 实际上直接记录市值更方便
                    ef["current_value"] = sf["current_value"]
                if sf.get("profit_loss") is not None:
                    ef["profit_loss"] = sf["profit_loss"]
                print(f"  🔄 更新: {ef['name']} ({code})")
            else:
                # 新增基金
                new_fund = {
                    "code": code,
                    "name": sf.get("name", f"基金{code}"),
                    "type": "未知",
                    "cost_nav": 1.00,  # 需要用户后续补充
                    "shares": 0,
                    "invested": sf.get("current_value", 0) if sf.get("current_value") else 0,
                    "buy_date": datetime.now().strftime("%Y-%m-%d"),
                    "note": "从截图导入"
                }
                existing["funds"].append(new_fund)
                existing_codes[code] = new_fund
                print(f"  ✨ 新增: {new_fund['name']} ({code})")

    else:
        # EasyOCR/PaddleOCR 结果，使用文本解析
        for fund in funds_found:
            code = fund["code"]
            if code in existing_codes:
                print(f"  🔄 发现: {existing_codes[code]['name']} ({code})")
            else:
                new_fund = {
                    "code": code,
                    "name": fund["name"],
                    "type": "未知",
                    "cost_nav": 1.00,
                    "shares": 0,
                    "invested": 0,
                    "buy_date": datetime.now().strftime("%Y-%m-%d"),
                    "note": "从截图导入，请手动补充成本和份额"
                }
                existing["funds"].append(new_fund)
                existing_codes[code] = new_fund
                print(f"  ✨ 新增: {fund['name']} ({code})")

    # 更新导入时间
    existing["last_import"] = datetime.now().isoformat()
    existing["import_method"] = "screenshot"
    if screenshot_data and isinstance(screenshot_data, dict):
        if screenshot_data.get("total_value"):
            existing["total_current_value"] = screenshot_data["total_value"]
        if screenshot_data.get("total_profit") is not None:
            existing["total_profit"] = screenshot_data["total_profit"]

    return existing


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="从支付宝截图导入基金持仓")
    parser.add_argument("images", nargs="*", help="截图文件路径")
    parser.add_argument("--method", choices=["easyocr", "paddle", "claude"],
                        default="easyocr", help="OCR 方法 (默认 easyocr)")
    parser.add_argument("--all", action="store_true",
                        help="识别 screenshots/ 目录下所有图片")
    parser.add_argument("--claude-key", help="Claude API Key (也可通过 ANTHROPIC_API_KEY 环境变量设置)")
    args = parser.parse_args()

    # 收集图片路径
    image_paths = []
    if args.all:
        if SCREENSHOTS_DIR.exists():
            image_paths = sorted(SCREENSHOTS_DIR.glob("*.png")) + \
                          sorted(SCREENSHOTS_DIR.glob("*.jpg")) + \
                          sorted(SCREENSHOTS_DIR.glob("*.jpeg"))
            print(f"📁 在 screenshots/ 中找到 {len(image_paths)} 张图片")
    elif args.images:
        for img in args.images:
            p = Path(img)
            if p.exists():
                image_paths.append(p)
            else:
                print(f"⚠️ 文件不存在: {img}")

    if not image_paths:
        print("请提供截图文件路径，或使用 --all 扫描 screenshots/ 目录")
        print("示例：")
        print("  python import_screenshot.py 支付宝截图.png")
        print("  python import_screenshot.py --all")
        print("  python import_screenshot.py --method claude 截图.png")
        return

    print(f"\n📷 准备识别 {len(image_paths)} 张截图\n")

    # 执行 OCR
    if args.method == "claude":
        if args.claude_key:
            os.environ["ANTHROPIC_API_KEY"] = args.claude_key
        result = ocr_with_claude(image_paths)
        if result:
            merged = merge_with_existing_config([], screenshot_data=result)
            save_funds(merged)
        return

    elif args.method == "paddle":
        raw_text = ocr_with_paddleocr(image_paths)
    else:  # easyocr
        raw_text = ocr_with_easyocr(image_paths)

    if not raw_text:
        print("\n❌ OCR 识别失败。建议尝试：")
        print("   1. python import_screenshot.py --method claude 截图.png")
        print("      (需要设置 ANTHROPIC_API_KEY 环境变量，识别最精准)")
        print("   2. 确保截图清晰，避免反光和遮挡")
        return

    # 解析文本
    print("\n📝 解析识别结果...")
    funds_found = parse_ocr_text(raw_text)

    if not funds_found:
        print("\n⚠️ 未能从截图中识别到基金代码。")
        print("   请确保截图包含支付宝基金持仓页面。")
        print("   原始识别文本已保存到 debug_ocr_output.txt")
        with open("debug_ocr_output.txt", "w", encoding="utf-8") as f:
            f.write(raw_text)
        return

    # 合并到配置
    print(f"\n🔍 识别到 {len(funds_found)} 只基金：")
    for fund in funds_found:
        print(f"   {fund['code']} - {fund['name']}")

    merged = merge_with_existing_config(funds_found)
    save_funds(merged)

    print("\n💡 提示：导入后请检查 funds.json 中的 cost_nav（买入成本）和 shares（份额）是否正确")
    print("   某些字段可能需要手动补充，尤其是通过 EasyOCR/PaddleOCR 识别的结果")


if __name__ == "__main__":
    main()
