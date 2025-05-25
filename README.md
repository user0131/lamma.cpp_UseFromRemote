# LlamaAPI - ロードバランサー型並列処理LLMサーバー

llama-cpp-pythonを利用したスケーラブル並列処理APIサーバーです。

## 主な機能

- **ロードバランサー**: 最大30の同時リクエスト処理
- **自動負荷分散**: ラウンドロビン方式
- **ヘルスチェック**: バックエンドサーバーの自動監視
- **OpenAI API互換**: `/v1/chat/completions`等
- **Metal GPU加速**: Mac環境での高速推論

## セットアップ

### 1. 依存関係のインストール

```bash
# 仮想環境をプロジェクト内に作成
poetry install --with llama-cpp-python

# Metal対応llama-cpp-pythonのインストール（Mac）
poetry run pip install --force-reinstall --no-cache-dir "cmake>=3.21.0"
CMAKE_ARGS="-DLLAMA_METAL=on" poetry run pip install --force-reinstall --no-cache-dir llama-cpp-python

# 追加パッケージ
source .venv/bin/activate
pip install aiohttp requests "uvicorn[standard]" fastapi
```

### 2. モデルのダウンロード

```bash
mkdir -p models

# Qwen3-4Bモデルのダウンロード（例)
curl -L https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf -o models/qwen3-4b.Q4_K_M.gguf

# Qwen3 8b 8Q
curl -L https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q8_K_M.gguf -o models/Qwen3-8b.Q8_K_M.gguf
```

## サーバー起動

### Step 0: (必要に応じて) 8070 ~ 9000のポートを解放
```bash
# portの使用状況を確認
lsof -i :8070-9000
# portの解放
lsof -ti :8070-9000 | xargs kill -9
```

### Step 1: バックエンドサーバー起動
```bash
source .venv/bin/activate
python src/start_backends.py models 0.0.0.0 8070 10  # 10台構成
```

### Step 2: ロードバランサー起動（別ターミナル）
```bash
source .venv/bin/activate
python src/load_balancer.py 0.0.0.0 8070 10 0.0.0.0 9000

# 30台対応（Mac Studio 512GB環境）
python src/load_balancer.py 0.0.0.0 8070 30 0.0.0.0 9000
```

### Step 3: 動作確認
```bash
curl http://localhost:9000/status

# 2. Bonjourホスト名（同じネットワーク内・macOS）
curl http://[LocalHostName].local:9000/status
# 例: curl http://big-llm-1.local:9000/status

# 3. IPアドレス（クロスプラットフォーム）
curl http://[IPアドレス]:9000/status
```

## API使用例

### OpenAI API互換

```bash
# チャット補完
curl -X POST http://localhost:9000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-4b.Q4_K_M.gguf",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "max_tokens": 50
  }'

# 構造化出力（カテゴリ分類）
curl -X POST http://localhost:9000/v1/beta/chat/completions/parse \
  -H "Content-Type: application/json" \
  -d @test/test_structured_output.json

# 構造化出力（シンプルテスト）
curl -X POST http://localhost:9000/v1/beta/chat/completions/parse \
  -H "Content-Type: application/json" \
  -d @test/simple_test.json

# 構造化出力(hawks: structure)
curl -X POST http://localhost:9000/v1/beta/chat/completions/parse \
  -H "Content-Type: application/json" \
  -d @test/tstructured_name_test.json
```

## メモリ使用量ガイド

| バックエンド数 | 推定メモリ使用量 | 推奨システム |
|-------------|---------------|-------------|
| 5台 | 約11.5GB | 16GB+ |
| 10台 | 約23GB | 32GB+ |
| 30台 | 約69GB | 512GB+ |

## エンドポイント

| エンドポイント | 説明 |
|---------------|------|
| `/status` | システム状態 |
| `/v1/models` | モデル一覧 |
| `/v1/chat/completions` | チャット補完 |
| `/v1/beta/chat/completions/parse` | 構造化出力 |

## プロジェクト構造

```
.
├── README.md
├── pyproject.toml
├── models/                     # モデルファイル
├── src/
│   ├── backend_server.py       # バックエンドサーバー
│   ├── start_backends.py       # バックエンド群起動
│   └── load_balancer.py        # ロードバランサー
└── test/
    ├── test_load_balancer.py   # テストスクリプト
    ├── test_structured_output.json  # 構造化出力テスト（カテゴリ分類）
    └── simple_test.json        # 構造化出力テスト（シンプルなテスト）
```

## テスト実行

```bash
source .venv/bin/activate

# 基本テスト
python test/test_load_balancer.py

# 構造化出力テスト
curl -X POST http://localhost:9000/v1/beta/chat/completions/parse \
  -H "Content-Type: application/json" \
  -d @test/test_structured_output.json
```