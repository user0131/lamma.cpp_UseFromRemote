# ComeAPI - Python版並列処理LLMサーバー

llama-cpp-pythonを利用した軽量な並列処理APIサーバーです。ollamaの代替として利用できます。

## 主な機能

- 複数リクエストの並列処理（スレッドプール方式）
- モデルの動的切り替えとキャッシュ機能
- FastAPIベースのREST API
- ネットワーク経由でのリモートアクセス対応
- Metal（Mac）/CUDA（NVIDIA）GPU加速対応

## セットアップ

### 1. 依存関係のインストール

```bash
# リポジトリをクローン
git clone https://github.com/your-username/comeapi-python.git
cd comeapi-python

# Poetryがインストールされていない場合
curl -sSL https://install.python-poetry.org | python3 -

# 仮想環境をプロジェクト内に作成
poetry config virtualenvs.in-project true

# 依存関係のインストール
poetry install --without llama-cpp-python --no-root

# Metal対応llama-cpp-pythonのインストール（Mac）
poetry run pip install --force-reinstall --no-cache-dir "cmake>=3.21.0"
CMAKE_ARGS="-DLLAMA_METAL=on" poetry run pip install --force-reinstall --no-cache-dir llama-cpp-python
```

### 2. モデルのダウンロード

```bash
# モデルディレクトリを作成
mkdir -p models

# Qwen3モデルのダウンロード例
curl -L https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf -o models/qwen3-4b.Q4_K_M.gguf
```

**推奨モデルサイズ:**
- **4B Q4_K_M**: ~2.5GB（8GBメモリ以上）
- **8B Q4_K_M**: ~4.5GB（16GBメモリ以上）
- **14B Q4_K_M**: ~8GB（32GBメモリ以上）

## 使用方法

### サーバー起動

```bash
# 仮想環境をアクティブ化
source .venv/bin/activate

# サーバー起動
python server.py <モデルディレクトリ> [ホスト] [ポート] [スレッド数] [ワーカー数]
```

**パラメータ:**
- `モデルディレクトリ`: GGUFファイルの配置場所（必須）
- `ホスト`: IPアドレス（デフォルト: 0.0.0.0）
- `ポート`: ポート番号（デフォルト: 8080）
- `スレッド数`: 各推論のCPUスレッド数（デフォルト: 4）
- `ワーカー数`: 同時処理リクエスト数（デフォルト: 4）

**起動例:**
```bash
# 8コア環境向け
python server.py ./models 0.0.0.0 8080 4 2

# 高性能環境向け（32コア）
python server.py ./models 0.0.0.0 8080 8 4
```

### API利用

#### cURLでの利用

```bash
# テキスト生成
curl -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Python並列処理について説明してください",
    "model_name": "qwen3-4b.Q4_K_M.gguf",
    "max_tokens": 512,
    "temperature": 0.8
  }'

# モデル一覧
curl http://localhost:8080/models
```

#### Pythonでの利用

```python
import requests

# テキスト生成
response = requests.post('http://localhost:8080/generate', json={
    "prompt": "Python並列処理について説明してください",
    "model_name": "qwen3-4b.Q4_K_M.gguf",
    "max_tokens": 512,
    "temperature": 0.8
})

print(response.json()['response'])
```

#### 直接ライブラリとして利用

```python
from come_api import LlamaAPI
import time

def print_result(result):
    print("結果:", result)

# APIの初期化
api = LlamaAPI(num_threads=4)
api.start(num_workers=2)

# テキスト生成
api.generate(
    prompt="Python並列処理について説明してください",
    model_path="./models/qwen3-4b.Q4_K_M.gguf",
    callback=print_result,
    max_tokens=512,
    temperature=0.8
)

# 完了を待機
while api.has_pending_tasks():
    time.sleep(0.1)

api.shutdown()
```

## API仕様

### エンドポイント

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/` | GET | サーバー状態確認 |
| `/models` | GET | モデル一覧取得 |
| `/generate` | POST | テキスト生成 |

### リクエストパラメータ（/generate）

| パラメータ | 型 | 必須 | デフォルト | 説明 |
|-----------|---|------|-----------|------|
| `prompt` | string | ✓ | - | 入力プロンプト |
| `model_name` | string | ✓ | - | モデルファイル名 |
| `max_tokens` | integer | - | 512 | 最大トークン数 |
| `temperature` | float | - | 0.8 | 生成温度 |
| `top_k` | integer | - | 40 | Top-k サンプリング |
| `top_p` | float | - | 0.9 | Top-p サンプリング |

## ハードウェア別推奨設定

| ハードウェア | スレッド数 | ワーカー数 | 設定例 |
|-------------|-----------|-----------|-------|
| 8コア | 4 | 2 | `python server.py ./models 0.0.0.0 8080 4 2` |
| 16コア | 8 | 2 | `python server.py ./models 0.0.0.0 8080 8 2` |
| 32コア | 8 | 4 | `python server.py ./models 0.0.0.0 8080 8 4` |

**原則**: `スレッド数 × ワーカー数 ≤ CPUコア数`

## パフォーマンス最適化

1. **GPU加速**: Metal（Mac）またはCUDA（NVIDIA）を有効化
2. **量子化モデル**: Q4_K_Mモデルでメモリ効率と速度のバランス
3. **並列設定**: ハードウェアに応じたスレッド/ワーカー数調整

## トラブルシューティング

**よくある問題:**
- **Port already in use**: 他のプロセスがポート8080を使用中
  ```bash
  lsof -i :8080  # プロセス確認
  kill -9 <PID>  # プロセス終了
  ```
- **Memory error**: モデルサイズがメモリ容量を超過
  → より小さなモデル（4B Q4_K_M）を使用

## 謝辞

- [llama-cpp-python](https://github.com/abetlen/llama-cpp-python) - llama.cppのPythonバインディング
- [FastAPI](https://fastapi.tiangolo.com/) - 高速APIフレームワーク
- [Poetry](https://python-poetry.org/) - Pythonパッケージ管理 