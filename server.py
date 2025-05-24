import os
import sys
import glob
import asyncio
import threading
import uvicorn
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from come_api import LlamaAPI

# APIリクエスト用のモデル
class GenerationRequest(BaseModel):
    prompt: str
    model_name: str
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32768)
    temperature: float = Field(default=0.8, ge=0, le=2.0)
    top_k: int = Field(default=40, ge=1, le=100)
    top_p: float = Field(default=0.9, ge=0, le=1.0)

# APIレスポンス用のモデル
class GenerationResponse(BaseModel):
    response: str

# エラーレスポンス用のモデル
class ErrorResponse(BaseModel):
    error: str

# モデル情報レスポンス用のモデル
class ModelInfo(BaseModel):
    name: str
    path: str
    size_mb: float

class ModelsResponse(BaseModel):
    models: List[ModelInfo]

# FastAPIアプリケーションの作成
app = FastAPI(
    title="ComeAPI",
    description="llama-cpp-pythonベースの並列処理API",
    version="1.0.0"
)

# CORSミドルウェアの設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# グローバル変数
models_dir = ""
api = None
pending_responses: Dict[str, str] = {}
responses_lock = threading.Lock()

# サーバーの初期化
def initialize_server(models_directory: str, num_threads: int, num_workers: int):
    global models_dir, api
    models_dir = models_directory
    
    # モデルディレクトリの確認
    if not os.path.isdir(models_dir):
        raise ValueError(f"モデルディレクトリが存在しません: {models_dir}")
    
    # APIの初期化
    api = LlamaAPI(num_threads=num_threads)
    api.start(num_workers=num_workers)

# 結果を受け取るコールバック関数
def store_response(client_id: str, result: str):
    global pending_responses
    with responses_lock:
        pending_responses[client_id] = result

# 結果の取得と削除
def get_and_remove_response(client_id: str) -> Optional[str]:
    global pending_responses
    with responses_lock:
        if client_id in pending_responses:
            result = pending_responses[client_id]
            del pending_responses[client_id]
            return result
    return None

# ルート
@app.get("/")
async def root():
    return {"message": "ComeAPI サーバーが実行中です"}

# モデル一覧の取得
@app.get("/models", response_model=ModelsResponse)
async def list_models():
    global models_dir
    
    models = []
    model_files = glob.glob(os.path.join(models_dir, "*.gguf"))
    
    for model_path in model_files:
        model_name = os.path.basename(model_path)
        model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
        models.append(ModelInfo(
            name=model_name,
            path=model_path,
            size_mb=round(model_size_mb, 2)
        ))
    
    return ModelsResponse(models=models)

# テキスト生成API
@app.post("/generate", response_model=GenerationResponse)
async def generate_text(request: GenerationRequest, background_tasks: BackgroundTasks):
    global api, models_dir
    
    if api is None:
        raise HTTPException(status_code=500, detail="サーバーが初期化されていません")
    
    # モデルパスの構築
    model_path = os.path.join(models_dir, request.model_name)
    
    # モデルの存在確認
    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail=f"モデルが見つかりません: {request.model_name}")
    
    # 非同期処理のためのイベントループと結果格納用の一意なID
    client_id = f"{id(request)}_{asyncio.get_event_loop().time()}"
    
    # テキスト生成のリクエスト
    api.generate(
        prompt=request.prompt,
        model_path=model_path,
        callback=lambda result: store_response(client_id, result),
        max_tokens=request.max_tokens if request.max_tokens is not None else 32768,
        temperature=request.temperature,
        top_k=request.top_k,
        top_p=request.top_p,
        client_id=client_id
    )
    
    # 結果が得られるまで待機
    result = None
    max_retries = 600  # 最大60秒（0.1秒 × 600）
    retries = 0
    
    while result is None and retries < max_retries:
        await asyncio.sleep(0.1)
        result = get_and_remove_response(client_id)
        retries += 1
    
    if result is None:
        raise HTTPException(status_code=500, detail="タイムアウト: 応答の生成に時間がかかりすぎています")
    
    # エラーメッセージのチェック
    if result.startswith("エラー") or result.startswith("モデルファイルが見つかりません"):
        raise HTTPException(status_code=500, detail=result)
    
    return GenerationResponse(response=result)

# サーバー起動関数
def start_server(models_directory: str, host: str = "0.0.0.0", port: int = 8080, 
                num_threads: int = 4, num_workers: int = 4):
    try:
        initialize_server(models_directory, num_threads, num_workers)
        uvicorn.run(app, host=host, port=port)
    finally:
        if api is not None:
            api.shutdown()

# メイン実行部分
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"使用方法: python {sys.argv[0]} <モデルディレクトリ> [ホスト=0.0.0.0] [ポート=8080] [スレッド数=4] [ワーカー数=4]")
        sys.exit(1)
    
    models_directory = sys.argv[1]
    host = sys.argv[2] if len(sys.argv) > 2 else "0.0.0.0"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 8080
    num_threads = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    num_workers = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    
    print(f"モデルディレクトリ: {models_directory}")
    print(f"ホスト: {host}")
    print(f"ポート: {port}")
    print(f"スレッド数: {num_threads}")
    print(f"ワーカー数: {num_workers}")
    
    start_server(models_directory, host, port, num_threads, num_workers) 