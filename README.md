# ComeAPI - ロードバランサー型並列処理LLMサーバー

llama-cpp-pythonを利用したスケーラブル並列処理APIサーバーです。リモートクライアントから最大30の同時リクエストを処理できます。

## 主な機能

- **ロードバランサー**: 最大30の同時リクエスト処理（8070-8099ポート）
- **自動負荷分散**: ラウンドロビン方式でリクエストを分散
- **ヘルスチェック**: バックエンドサーバーの自動監視・復旧（30秒間隔）
- **FastAPIベース**: 標準的なREST API
- **リモートアクセス**: ネットワーク経由での安全な利用
- **Metal GPU加速**: Mac環境での高速推論
- **シンプル構成**: 必要最小限のファイル構成
- **スケーラブル**: 5台〜30台まで柔軟な設定

## 🏗️ システム構成

```
Remote Client PC ─── Network ─── Load Balancer (port 9000) ─── Backend 1 (port 8070)
                                                             ├── Backend 2 (port 8071)
                                                             ├── Backend 3 (port 8072)
                                                             ├── ...
                                                             └── Backend 30 (port 8099)
```

## 📋 前提条件

- Python 3.8以上
- Poetry（パッケージ管理）
- macOS推奨（Metal GPU加速対応）
- **32GB以上のRAM**（10台構成時）**512GB推奨**（30台構成時・Mac Studio）
- **空きポート**: 8070-8099, 9000
- **ネットワーク**: リモートアクセス用のファイアウォール設定

## セットアップ

### 1. 依存関係のインストール

```bash
# リポジトリをクローン
git clone https://github.com/user0131/lamma.cpp_UseFromRemote.git
cd lamma.cpp_UseFromRemote

# 仮想環境をプロジェクト内に作成
poetry config virtualenvs.in-project true

# 依存関係のインストール
poetry install --with llama-cpp-python

# Metal対応llama-cpp-pythonのインストール（Mac）
poetry run pip install --force-reinstall --no-cache-dir "cmake>=3.21.0"
CMAKE_ARGS="-DLLAMA_METAL=on" poetry run pip install --force-reinstall --no-cache-dir llama-cpp-python

# 必要なパッケージの追加インストール
pip install aiohttp requests
```

### 2. モデルのダウンロード

```bash
# モデルディレクトリを作成
mkdir -p models

# Qwen3-4Bモデルのダウンロード（推奨）
curl -L https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf -o models/qwen3-4b.Q4_K_M.gguf
```

## 💻 サーバー起動

### 🚀 システム起動手順

#### Step 1: 仮想環境のアクティブ化
```bash
# 必須：仮想環境をアクティブ化
source .venv/bin/activate
```

#### Step 2: バックエンドサーバー起動
```bash
# バックエンドサーバー群起動（デフォルト5台: 8070-8074）
python src/start_backends.py models

# 10台で起動（8070-8079）推奨：32GB環境
python src/start_backends.py models 0.0.0.0 8070 10

# 最大30台で起動（8070-8099）推奨：Mac Studio 512GB環境
python src/start_backends.py models 0.0.0.0 8070 30
```

#### Step 3: ロードバランサー起動（別ターミナル）
```bash
# 新しいターミナルで仮想環境をアクティブ化
source .venv/bin/activate

# ロードバランサー起動（リモートアクセス対応）
python src/load_balancer.py 0.0.0.0 8070 5 0.0.0.0 9000

# 30台対応（Mac Studio 512GB環境）
python src/load_balancer.py 0.0.0.0 8070 30 0.0.0.0 9000
```

#### Step 4: 動作確認
```bash
# ローカル動作確認
curl http://localhost:9000/

# リモートアクセス確認（サーバーIPアドレスを指定）
curl http://[サーバーIPアドレス]:9000/
```

### ⚠️ 重要な注意点
1. **仮想環境**: 必ず `source .venv/bin/activate` を実行
2. **実行場所**: プロジェクトのルートディレクトリから実行
3. **モデルパス**: `models` でルートのmodelsディレクトリを指定
4. **依存関係**: aiohttp, requestsが必要（pip install）
5. **起動順序**: バックエンド → ロードバランサーの順序必須
6. **ポート確認**: 8070-8099, 9000が空いていることを確認
7. **ターミナル**: バックエンドとロードバランサーは別ターミナルで起動
8. **長期間実行**: ログ出力無効化済み（ディスク使用量増加なし）
9. **メモリ使用量**: バックエンド数 × 2.3GB（Qwen3-4B使用時）
10. **Mac Studio**: 512GBメモリ環境で30台並列処理に最適化
11. **リモートアクセス**: バックエンドとロードバランサーで `0.0.0.0` を指定

## 🌐 ネットワーク設定

### ファイアウォール設定

#### macOS
```bash
# ポート開放（8070-8099, 9000）
sudo pfctl -f /etc/pf.conf
sudo pfctl -e

# 一時的なポート開放
sudo pfctl -d  # 無効化（開発時のみ）
```

#### 手動でのポート確認
```bash
# ポート使用状況確認
lsof -i :8070-8099
lsof -i :9000

# ネットワーク接続確認
netstat -an | grep LISTEN | grep -E ":(8070|8071|8072|8073|8074|9000)"
```

### サーバーIPアドレスの確認
```bash
# ローカルIPアドレス確認
ifconfig | grep "inet " | grep -v 127.0.0.1

# または
ipconfig getifaddr en0  # Wi-Fi
ipconfig getifaddr en1  # 有線LAN
```

## 🌐 リモートクライアントからの利用

### 基本的な使用例

```bash
# サーバーIPアドレスを192.168.1.100と仮定

# システム状態確認
curl http://192.168.1.100:9000/status

# モデル一覧
curl http://192.168.1.100:9000/models

# テキスト生成
curl -X POST http://192.168.1.100:9000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "qwen3-4b.Q4_K_M.gguf",
    "prompt": "リモートから接続テスト",
    "max_tokens": 50
  }'
```

### Pythonクライアント例

```python
import requests

# サーバーIPアドレスを設定
SERVER_IP = "192.168.1.100"  # 実際のサーバーIPに変更
API_URL = f"http://{SERVER_IP}:9000"

# テキスト生成
response = requests.post(f'{API_URL}/generate', json={
    "prompt": "Pythonでリモートアクセステスト",
    "model_name": "qwen3-4b.Q4_K_M.gguf",
    "max_tokens": 200,
    "temperature": 0.8
})

result = response.json()
print(result['response'])

# システム状態確認
status = requests.get(f'{API_URL}/status').json()
print(f"稼働中バックエンド: {status['healthy_backends']}/{status['total_backends']}")
```

### JavaScript/Node.js クライアント例

```javascript
const axios = require('axios');

const SERVER_IP = "192.168.1.100";  // 実際のサーバーIPに変更
const API_URL = `http://${SERVER_IP}:9000`;

async function generateText() {
    try {
        const response = await axios.post(`${API_URL}/generate`, {
            prompt: "JavaScriptからのリモートアクセステスト",
            model_name: "qwen3-4b.Q4_K_M.gguf",
            max_tokens: 200,
            temperature: 0.8
        });
        
        console.log(response.data.response);
    } catch (error) {
        console.error('エラー:', error.message);
    }
}

generateText();
```

## 💾 メモリ使用量ガイド

| バックエンド数 | 推定メモリ使用量 | 推奨システム | 用途 |
|-------------|---------------|-------------|-----|
| 5台 | 約11.5GB | 16GB+ | 開発・テスト環境 |
| 10台 | 約23GB | 32GB+ | 32GBメモリ環境の最適構成 |
| 15台 | 約34.5GB | 64GB+ | 高性能ワークステーション |
| 20台 | 約46GB | 64GB+ | 大規模本番環境 |
| **30台** | **約69GB** | **512GB+** | **Mac Studio推奨構成** |

### 🖥️ **環境別推奨構成**

| 環境 | メモリ | 推奨バックエンド数 | 期待性能 |
|-----|------|---------------|---------|
| 開発環境 | 16GB | 5台 | 基本利用 |
| **汎用環境** | **32GB** | **10台** | **バランス重視** |
| ワークステーション | 64GB | 15-20台 | 高性能 |
| **Mac Studio** | **512GB** | **30台** | **最大性能** |

## 📊 API仕様

### エンドポイント

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/` | GET | ロードバランサー状態 |
| `/status` | GET | 詳細なシステム状態 |
| `/models` | GET | 利用可能モデル一覧 |
| `/generate` | POST | テキスト生成 |

### リクエストパラメータ（/generate）

| パラメータ | 型 | 必須 | デフォルト | 説明 |
|-----------|---|------|-----------|------|
| `prompt` | string | ✓ | - | 入力プロンプト |
| `model_name` | string | ✓ | - | モデルファイル名 |
| `max_tokens` | integer | - | 100 | 最大トークン数 |
| `temperature` | float | - | 0.8 | 生成温度 |
| `top_k` | integer | - | 40 | Top-k サンプリング |
| `top_p` | float | - | 0.9 | Top-p サンプリング |

## トラブルシューティング

### 1. モジュールエラー
**症状**: `ModuleNotFoundError: No module named 'aiohttp'`

**解決策**:
```bash
source .venv/bin/activate
pip install aiohttp requests
```

### 2. リモート接続エラー
**症状**: `Connection refused` または接続タイムアウト

**解決策**:
```bash
# 1. サーバー側でバインドアドレス確認
python src/start_backends.py models 0.0.0.0 8070 5  # 0.0.0.0を指定
python src/load_balancer.py 0.0.0.0 8070 5 0.0.0.0 9000

# 2. ファイアウォール確認
sudo pfctl -d  # 一時的に無効化（開発時のみ）

# 3. ポート確認
lsof -i :9000
```

### 3. バックエンド接続エラー
**症状**: `503 Service Unavailable` または `502 Bad Gateway`

**解決策**:
```bash
# バックエンド状態確認
curl http://[サーバーIP]:8070/
curl http://[サーバーIP]:8071/
curl http://[サーバーIP]:9000/status
```

### 4. メモリ不足エラー
**症状**: `OutOfMemoryError` または異常に遅い応答

**解決策**:
```bash
# メモリ使用量確認
ps aux | grep "python.*server.py" | awk '{sum += $6} END {print "Total Memory: " sum/1024 " MB"}'

# バックエンド数を削減
python src/start_backends.py models 0.0.0.0 8070 5
```

## 📂 プロジェクト構造（必要最小限）

```
.
├── README.md                   # ネットワーク設定ドキュメント
├── pyproject.toml              # Poetry設定
├── poetry.lock                 # 依存関係ロック
├── .gitignore                  # 除外設定
├── models/                     # モデルファイル
│   └── qwen3-4b.Q4_K_M.gguf   # Qwen3-4Bモデル
├── .venv/                      # 仮想環境
├── .git/                       # Git管理
├── src/                        # ソースコード
│   ├── backend_server.py       # バックエンドサーバー
│   ├── start_backends.py       # バックエンド群起動スクリプト
│   └── load_balancer.py        # ロードバランサー本体
└── test/                       # テストコード
    └── test_load_balancer.py   # ロードバランサーテストスイート
```

## 🚀 クイックスタート

### 基本構成（5台）
```bash
# 1. 仮想環境アクティブ化
source .venv/bin/activate

# 2. バックエンドサーバー起動
python src/start_backends.py models 0.0.0.0 8070 5

# 3. 新しいターミナルでロードバランサー起動
source .venv/bin/activate
python src/load_balancer.py 0.0.0.0 8070 5 0.0.0.0 9000

# 4. リモートから動作確認
curl http://[サーバーIP]:9000/status
```

### Mac Studio（30台）構成
```bash
# 1. Mac Studio 512GBメモリ確認
system_profiler SPHardwareDataType | grep Memory

# 2. 30台バックエンド起動
python src/start_backends.py models 0.0.0.0 8070 30

# 3. 対応ロードバランサー起動
python src/load_balancer.py 0.0.0.0 8070 30 0.0.0.0 9000
```

### 32GB環境（10台）構成
```bash
# 1. 32GBメモリ環境での推奨構成
python src/start_backends.py models 0.0.0.0 8070 10

# 2. 対応ロードバランサー起動
python src/load_balancer.py 0.0.0.0 8070 10 0.0.0.0 9000
```