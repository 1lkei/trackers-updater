# Tracker 列表更新器

从配置的公开 Tracker 源获取列表、去重，并生成三种格式。

## 配置

编辑 `config/tracker_url_list.txt`，每行一个 HTTP 或 HTTPS URL。空行和以 `#` 开头的行会被忽略。

## 输出

生成文件位于 `output/`：

- `trackers_list_comma.txt`：逗号分隔
- `trackers_list_newline.txt`：每行一个
- `trackers_list_blankline.txt`：空行分隔

## 本地运行

```bash
python -m venv .venv
```

激活环境后执行：Windows PowerShell 使用 `.venv\Scripts\Activate.ps1`；macOS／Linux 使用 `source .venv/bin/activate`。

```bash
python -m pip install -r requirements.txt
python main.py
```

## 自动运行

GitHub Actions 每天北京时间 00:00 运行，也可在 Actions 页面手动触发。

工作流只在输出内容变化时提交三个生成文件。获取源失败时，Actions 页面会显示失败 URL 的警告；提交信息包含运行日期与失败源数量。
