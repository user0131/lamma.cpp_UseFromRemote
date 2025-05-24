#!/usr/bin/env python3
"""
Backend Server for Load Balancer System
シンプルなバックエンドサーバー（ロードバランサー用）
"""

import os
import sys
import glob
import uvicorn
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from llama_cpp import Llama

# APIリクエスト用のモデル
class GenerationRequest(BaseModel):
    prompt: str
    model_name: str
    max_tokens: Optional[int] = Field(default=100, ge=1, le=32768)
    temperature: float = Field(default=0.8, ge=0, le=2.0)
    top_k: int = Field(default=40, ge=1, le=100)
    top_p: float = Field(default=0.9, ge=0, le=1.0)

# APIレスポンス用のモデル
class GenerationResponse(BaseModel):
    response: str

# モデル情報レスポンス用のモデル
class ModelInfo(BaseModel):
    name: str
    path: str
    size_mb: float

class ModelsResponse(BaseModel):
    models: List[ModelInfo]

# FastAPIアプリケーションの作成
app = FastAPI(
    title="Backend Server",
    description="ロードバランサー用バックエンドサーバー",
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
llama_model: Optional[Llama] = None
current_model_path = ""

def initialize_server(models_directory: str, num_threads: int):
    """サーバーの初期化"""
    global models_dir
    models_dir = models_directory
    
    # モデルディレクトリの確認
    if not os.path.isdir(models_dir):
        raise ValueError(f"モデルディレクトリが存在しません: {models_dir}")
    
    print(f"✅ Backend Server initialized")
    print(f"   📁 Models directory: {models_dir}")
    print(f"   🧵 Threads: {num_threads}")

def load_model(model_path: str, num_threads: int) -> Llama:
    """モデルをロード（キャッシュ機能付き）"""
    global llama_model, current_model_path
    
    # 既に同じモデルがロードされている場合はそのまま使用
    if llama_model is not None and current_model_path == model_path:
        return llama_model
    
    # 新しいモデルをロード
    print(f"🔄 Loading model: {os.path.basename(model_path)}")
    llama_model = Llama(
        model_path=model_path,
        n_ctx=2048,
        n_threads=num_threads,
        verbose=False
    )
    current_model_path = model_path
    print(f"✅ Model loaded successfully")
    return llama_model

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
async def generate_text(request: GenerationRequest):
    global models_dir
    
    # モデルパスの構築
    model_path = os.path.join(models_dir, request.model_name)
    
    # モデルの存在確認
    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail=f"モデルが見つかりません: {request.model_name}")
    
    try:
        # モデルのロード
        model = load_model(model_path, num_threads=1)  # バックエンドは1スレッドで安定動作
        
        # テキスト生成
        result = model.create_completion(
            prompt=request.prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_k=request.top_k,
            top_p=request.top_p,
            stream=False
        )
        
        # 結果の取得
        generated_text = result["choices"][0]["text"]
        return GenerationResponse(response=generated_text)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成エラー: {str(e)}")

# サーバー起動関数
def start_server(models_directory: str, host: str = "127.0.0.1", port: int = 8080, 
                num_threads: int = 1):
    """バックエンドサーバーを起動"""
    try:
        initialize_server(models_directory, num_threads)
        # CPU使用率を最小化する設定
        uvicorn.run(
            app, 
            host=host, 
            port=port,
            workers=1,              # ワーカー数を1に制限
            loop="asyncio",         # asyncioループを使用
            access_log=False,       # アクセスログを無効化
            log_level="error"       # エラーログのみ出力
        )
    except KeyboardInterrupt:
        print("🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Server error: {e}")

# メイン実行部分
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"使用方法: python {sys.argv[0]} <モデルディレクトリ> [ホスト=127.0.0.1] [ポート=8080] [スレッド数=1]")
        print(f"例: python {sys.argv[0]} ./models")
        print(f"例: python {sys.argv[0]} ./models 127.0.0.1 8080 1")
        sys.exit(1)
    
    models_directory = sys.argv[1]
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 8080
    num_threads = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    
    print("="*50)
    print("🖥️  Backend Server")
    print("="*50)
    print(f"📁 モデルディレクトリ: {models_directory}")
    print(f"🌐 ホスト: {host}")
    print(f"🔌 ポート: {port}")
    print(f"🧵 スレッド数: {num_threads}")
    print("="*50)
    
    start_server(models_directory, host, port, num_threads) 