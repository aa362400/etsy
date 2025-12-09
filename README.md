一个用于将本地商品数据自动上架到 Etsy 商店的 Python 命令行工具。脚本提供「绑定店铺 + 自动刷新令牌」的授权流程，避免手动管理 Access Token，授权一次即可反复上架商品。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 绑定店铺（一次操作）

1. 在 [Etsy 开发者后台](https://www.etsy.com/developers/) 创建应用，记下 `client_id`（旧版称 API Key）。
2. 运行授权命令，脚本会启动本地回调服务器并自动交换令牌，完成后把令牌缓存到 `~/.etsy_tokens.json`：
   ```bash
   python etsy_lister.py auth \
     --client-id "$ETSY_CLIENT_ID" \
     --redirect-port 8787 \
     --scopes "listings_r listings_w shops_r transactions_r"
   ```
   *保持终端运行，浏览器打开打印出来的授权链接，允许访问后等待终端提示「Tokens saved」。*
3. 如需更换保存位置，可传 `--token-file /path/to/tokens.json` 或设置环境变量 `ETSY_TOKEN_FILE`。
4. 令牌过期时脚本会自动用 `refresh_token` 续期，无需手动干预。

## 准备商品文件

复制 `samples/product.yaml` 按实际信息修改。核心字段：
- `title`、`description`、`price`、`quantity`
- `taxonomy_id`、`who_made`、`when_made`、`is_supply`
- `shipping_profile_id`、`return_policy_id`
- `tags`、`materials`、`images`（本地路径 + 可选 `alt_text`）

文件支持 YAML 或 JSON，更多可选字段见 `etsy_lister.py` 中的 `optional_fields` 列表。

## 上架商品

```bash
python etsy_lister.py list \
  --product-file ./samples/product.yaml \
  --shop-id 123456789 \
  --publish \
  --verbose
```

- 首次会自动从 `~/.etsy_tokens.json` 读取 Access Token，必要时刷新并覆盖保存。
- `--dry-run` 仅打印 payload 与图片信息，不调用接口。
- `--skip-images` 跳过图片上传（排查字段时有用）。

## 打包成桌面应用

如果希望给运营同事一个「双击可用」的工具，可用 PyInstaller 打包：

1. 安装打包依赖：`pip install -r requirements-packaging.txt`。
2. 执行 `./scripts/build_executable.sh`（或 Windows 下运行对应命令）。
3. 打包结果在 `dist/etsy-lister`（Windows 为 `dist/etsy-lister.exe`）。首次运行前同样需要执行一次 `auth` 命令生成令牌文件，然后携带该文件一起分发。

## 故障排查
- 无法捕获授权？确认防火墙未阻止本地端口（默认 8787），或改用 `--redirect-port` 指定其他端口。
- `listing_id` 未返回会抛出错误并打印完整响应，可据此调整字段。
- 上传图片失败多与路径或尺寸限制有关，日志会打印 HTTP 状态码以便定位。
