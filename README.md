# Etsy 自动上架脚本

一个用于将本地商品数据自动上架到 Etsy 商店的 Python 命令行工具。脚本使用 Etsy V3 Open API，通过 YAML/JSON 定义文件创建草稿、上传图片并可选发布。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 准备工作

1. 在 [Etsy 开发者后台](https://www.etsy.com/developers/) 创建应用，获取 API Key，并完成 OAuth 获得访问令牌。
2. 将下列环境变量写入 shell 或 `.env`：
   - `ETSY_API_KEY`
   - `ETSY_ACCESS_TOKEN`
   - `ETSY_SHOP_ID`（可选，命令行未指定时的默认店铺 ID）
3. 复制 `samples/product.yaml`，按实际商品信息调整，主要字段：
   - `title`、`description`、`price`、`quantity`
   - `taxonomy_id`、`who_made`、`when_made`、`is_supply`
   - `shipping_profile_id`、`return_policy_id`
   - `tags`、`materials`、`images`（图片路径与可选 `alt_text`）

## 使用示例

创建草稿并打印 payload：

```bash
python etsy_lister.py --product-file ./samples/product.yaml --dry-run
```

创建草稿并上传图片：

```bash
python etsy_lister.py \
  --product-file ./samples/product.yaml \
  --shop-id 123456789 \
  --api-key "$ETSY_API_KEY" \
  --access-token "$ETSY_ACCESS_TOKEN"
```

创建后直接发布：

```bash
python etsy_lister.py \
  --product-file ./samples/product.yaml \
  --publish \
  --verbose
```

### 常用参数
- `--publish`：上传图片后立即发布，默认创建草稿。
- `--skip-images`：只创建 listing，不上传图片（便于测试）。
- `--verbose`：输出详细日志（API 请求步骤等）。

## 如何做成应用/可执行软件

如果希望在没有 Python 环境的电脑上直接运行，或给运营同事一个可双击的工具，可以用 PyInstaller 打包成单文件程序：

1. 安装打包依赖：`pip install -r requirements-packaging.txt`。
2. 运行打包脚本：`./scripts/build_executable.sh`（Windows 可用 Git Bash 或 WSL；如使用原生 PowerShell，可执行 `pyinstaller --name etsy-lister --onefile --add-data "samples/product.yaml;samples" etsy_lister.py`）。
3. 打包结果在 `dist/etsy-lister`（Windows 为 `dist/etsy-lister.exe`），可拷贝到任意机器使用。
4. 运行时依然需要 Etsy API 凭据，可将环境变量写入同目录下的 `.env`：
   ```env
   ETSY_API_KEY=...
   ETSY_ACCESS_TOKEN=...
   ETSY_SHOP_ID=...
   ```
   然后执行：`./etsy-lister --product-file my_product.yaml --publish`。

### 常见需求

- **给非技术同事使用**：在 `dist/` 内为可执行文件创建桌面快捷方式，并把已填好的商品模板一并放入同一文件夹。
- **定时上架**：将打包后的命令加入计划任务（Windows 任务计划程序、macOS `launchd` 或 Linux `cron`），触发命令中指定好 `--product-file`。
- **可视化界面**：如需表单式操作，可在现有脚本基础上用 Streamlit 或 Tkinter 包一层简单 GUI，再用同样的 PyInstaller 命令重新打包。

## 商品文件格式

商品文件支持 YAML 或 JSON。关键字段如下（更多可选字段见 `etsy_lister.py` 中的 `optional_fields` 列表）：

```yaml
title: "手工真丝发带"
description: "..."
price: "28.00"
quantity: 5
taxonomy_id: 1118
who_made: i_did
when_made: made_to_order
is_supply: false
shipping_profile_id: 123456789
return_policy_id: 987654321
tags: ["真丝", "发带", "手工"]
materials: ["silk", "elastic"]
images:
  - path: ./images/sample-headband.jpg
    alt_text: "白色背景上的真丝发带"
```

## 故障排查
- 如果返回 401/403，确认 API Key、Access Token 以及应用权限正确。
- `listing_id` 未返回时会抛出错误并打印完整响应，可据此调整字段。
- 上传图片失败通常与文件路径或尺寸限制有关，日志中会显示具体 HTTP 状态码。
