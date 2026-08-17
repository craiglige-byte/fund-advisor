# 基金日报助手

每日自动分析基金持仓，给出操作建议。

## 功能

- ✅ **支付宝截图导入** — 截图自动识别基金和持仓
- ✅ **每日净值抓取** — 自动获取最新净值和涨跌
- ✅ **智能分析** — 综合盈亏、表现、市场环境给出建议
- ✅ **H5 报告** — 手机友好的日报页面
- ✅ **自动推送** — GitHub Actions 每个交易日自动生成

## 项目结构

```
fund-advisor/
├── funds.json              # 基金持仓配置
├── generate_report.py      # 日报生成脚本（核心）
├── import_screenshot.py    # 支付宝截图导入脚本
├── index.html              # 生成的日报（自动更新）
├── screenshots/            # 放支付宝截图
├── requirements.txt        # Python 依赖
└── .github/workflows/      # 自动运行配置
```

## 使用流程

### 1. 导入持仓

> 方法一：支付宝截图（推荐）
> 1. 打开支付宝 → 理财 → 基金 → 截屏
> 2. 把截图放到 `screenshots/` 目录
> 3. 运行：`python import_screenshot.py --all`
> 4. 检查 `funds.json` 中的买入成本是否正确

> 方法二：直接编辑 funds.json

### 2. 生成日报

```bash
# 安装依赖
pip install requests

# 生成日报
python generate_report.py

# 用浏览器打开 index.html 查看
```

### 3. 部署自动运行（可选）

1. 把项目上传到 GitHub
2. GitHub Actions 会在每个交易日 15:30 自动运行
3. 生成的 index.html 可通过 GitHub Pages 访问

推送通知可配置：
- Telegram Bot（免费）
- Server酱（微信推送，免费额度）
- 邮件通知

## 依赖

- Python 3.9+
- requests
- akshare（可选，用于 PE/PB 估值）
- easyocr（可选，用于截图 OCR）

## 数据来源

所有数据来自公开免费接口：
- 基金净值/涨跌 → 东方财富 API
- 市场指数 → 东方财富行情接口
- PE/PB 估值 → AKShare（可选）

## 免责声明

⚠️ 仅供参考，不构成投资建议。投资有风险，买卖需谨慎。
