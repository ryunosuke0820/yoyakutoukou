# FANZA → WordPress 自動記事投稿ボット

FANZA/DMMの商品情報を取得し、Claude Opus 4.5で記事を生成、WordPressに下書き投稿する自動化ツール。

## 特徴

- **重複投稿100%防止**: SQLiteで投稿済み作品をトラッキング
- **品質チェック**: 文字数、禁止ワード、構成のバリデーション
- **観点カード**: 毎回ランダムな観点で記事に変化を出す
- **cron対応**: 1コマンドで完結、失敗しても止まらない

## セットアップ

### 1. 依存パッケージのインストール

```powershell
cd C:\Users\ryuno\.gemini\antigravity\scratch\fanza-wp-bot
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env.example` をコピーして `.env` を作成し、各値を設定:

```powershell
copy .env.example .env
```

```ini
# FANZA/DMM API
FANZA_API_KEY=your_api_key
FANZA_AFFILIATE_ID=your_affiliate_id

# WordPress REST API
WP_BASE_URL=https://your-site.com
WP_USERNAME=your_username
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx

# Anthropic Claude API
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-opus-4-5-20250514

# 記事生成設定
MIN_CHARS=800
MAX_CHARS=1500
POST_STATUS=draft
```

### 3. WordPressアプリケーションパスワードの取得

1. WordPress管理画面にログイン
2. ユーザー → プロフィール
3. 「アプリケーションパスワード」セクションで新規作成
4. 生成されたパスワードを `WP_APP_PASSWORD` に設定

## 使い方

### 基本実行

```powershell
python main.py --limit 10
```

### ドライラン（WP投稿なし）

```powershell
python main.py --limit 5 --dry-run --log-level DEBUG
```

### 日付指定

```powershell
python main.py --limit 10 --since 2026-01-01
```

### 失敗項目のリトライ

```powershell
python main.py --limit 10 --clear-failed
```

## CLI引数

| 引数 | 説明 | デフォルト |
|------|------|------------|
| `--limit N` | 取得件数 | 10 |
| `--dry-run` | WP投稿せず生成のみ | false |
| `--since YYYY-MM-DD` | 指定日以降の作品 | なし |
| `--log-level` | DEBUG/INFO/WARNING/ERROR | INFO |
| `--clear-failed` | 失敗項目をクリア | false |

## cron設定例

毎日午前3時に5件処理:

```
# crontab -e
0 3 * * * cd /path/to/fanza-wp-bot && python main.py --limit 5 >> cron.log 2>&1
```

Windows タスクスケジューラ:
1. 「タスクの作成」
2. トリガー: 毎日 3:00
3. 操作: `python` 引数: `C:\path\to\main.py --limit 5`

## プロジェクト構成

```
fanza-wp-bot/
├── main.py              # CLIエントリポイント
├── config.py            # 環境変数読み込み
├── fanza_client.py      # FANZA API呼び出し
├── claude_client.py     # Claude記事生成
├── dedupe_store.py      # SQLite重複防止
├── validator.py         # 品質チェック
├── wp_client.py         # WordPress投稿
├── image_tools.py       # 画像処理
├── prompts/
│   ├── system.txt       # Claudeシステムプロンプト
│   └── user.txt         # ユーザープロンプトテンプレート
├── viewpoints.json      # 観点カード（20個）
├── banned_words.txt     # 禁止ワード
├── data/
│   └── posted.sqlite3   # 投稿済みDB（自動生成）
├── requirements.txt
├── .env.example
└── README.md
```

## 開発Tips

### コマンド実行について

**OpenAI API呼び出しは20〜30秒かかる**ため、以下の使い分けを推奨:

| 作業 | 推奨環境 |
|------|----------|
| `main.py` の実行 | **VS Code ターミナル** |
| コードの編集・確認 | Antigravity (AI) |

> [!NOTE]
> Antigravity でコマンド実行すると「Working」表示が残り続けることがあります。
> 長時間かかる処理は VS Code ターミナルで直接実行してください。

## トラブルシューティング

### API呼び出しエラー

- **429 Rate Limit**: 自動リトライします。頻発する場合は `--limit` を減らす
- **タイムアウト**: ネットワーク確認、60秒でタイムアウト設定

### 品質チェック失敗

- `data/posted.sqlite3` を確認、`status=failed` の項目を確認
- `--clear-failed` で再試行可能に

### WordPress投稿エラー

- アプリケーションパスワードを再確認
- REST APIが有効か確認（一部プラグインで無効化される）

## 拡張ポイント（将来）

- [ ] 画像文字入れ (`image_tools.py` の `add_text_overlay`)
- [ ] 関連記事内部リンク
- [ ] 予約投稿（`POST_STATUS=future` + `date` パラメータ）
- [ ] 複数サイト対応
- [ ] メール通知（成功/失敗サマリー）

## ライセンス

MIT
