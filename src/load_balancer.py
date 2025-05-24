#!/usr/bin/env python3
"""
ComeAPI ロードバランサー
複数のバックエンドサーバー間でリクエストを負荷分散
"""

import asyncio
import aiohttp
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Backend:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}"
        self.is_healthy = True
        self.last_check = 0
        self.response_times: List[float] = []
        self.error_count = 0
        
    def add_response_time(self, response_time: float):
        """レスポンス時間を記録"""
        self.response_times.append(response_time)
        # 最新10件のみ保持
        if len(self.response_times) > 10:
            self.response_times.pop(0)
    
    def get_average_response_time(self) -> float:
        """平均レスポンス時間を取得"""
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)
    
    def mark_error(self):
        """エラーをマーク"""
        self.error_count += 1
        if self.error_count >= 3:
            self.is_healthy = False
    
    def mark_success(self):
        """成功をマーク"""
        self.error_count = 0
        self.is_healthy = True
    
    def __str__(self):
        return f"Backend({self.url}, healthy={self.is_healthy}, errors={self.error_count})"

class LoadBalancer:
    def __init__(self, backends: List[Backend]):
        self.backends = backends
        self.current_index = 0
        self.session = None
        
    async def init_session(self):
        """HTTP セッションを初期化"""
        if self.session is None:
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=20)
            timeout = aiohttp.ClientTimeout(total=120)
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    
    async def close_session(self):
        """HTTP セッションを閉じる"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def health_check(self, backend: Backend) -> bool:
        """バックエンドのヘルスチェック"""
        try:
            await self.init_session()
            start_time = time.time()
            async with self.session.get(f"{backend.url}/") as response:
                response_time = time.time() - start_time
                backend.add_response_time(response_time)
                
                if response.status == 200:
                    backend.mark_success()
                    backend.last_check = time.time()
                    return True
                else:
                    backend.mark_error()
                    return False
                    
        except Exception as e:
            logger.warning(f"Backend {backend.url} ヘルスチェック失敗: {e}")
            backend.mark_error()
            return False
    
    async def health_check_all(self):
        """全バックエンドのヘルスチェック"""
        current_time = time.time()
        tasks = []
        
        for backend in self.backends:
            # 30秒ごとにヘルスチェック
            if current_time - backend.last_check > 30:
                tasks.append(self.health_check(backend))
            
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def get_next_backend(self) -> Optional[Backend]:
        """次の利用可能なバックエンドを取得 (ラウンドロビン)"""
        healthy_backends = [b for b in self.backends if b.is_healthy]
        
        if not healthy_backends:
            return None
            
        # ラウンドロビン方式
        backend = healthy_backends[self.current_index % len(healthy_backends)]
        self.current_index = (self.current_index + 1) % len(healthy_backends)
        
        return backend
    
    async def forward_request(self, method: str, path: str, **kwargs) -> Tuple[int, Dict[str, Any]]:
        """リクエストをバックエンドに転送"""
        backend = self.get_next_backend()
        if not backend:
            raise HTTPException(status_code=503, detail="利用可能なバックエンドサーバーがありません")
        
        url = f"{backend.url}{path}"
        
        try:
            await self.init_session()
            start_time = time.time()
            
            async with self.session.request(method, url, **kwargs) as response:
                response_time = time.time() - start_time
                backend.add_response_time(response_time)
                
                result = await response.json()
                
                if response.status == 200:
                    backend.mark_success()
                    logger.info(f"✅ Request forwarded to {backend.url} (took {response_time:.2f}s)")
                else:
                    backend.mark_error()
                    logger.warning(f"⚠️  Backend {backend.url} returned status {response.status}")
                
                return response.status, result
                
        except Exception as e:
            backend.mark_error()
            logger.error(f"❌ Backend {backend.url} request failed: {e}")
            # 別のバックエンドで再試行
            other_backend = self.get_next_backend()
            if other_backend and other_backend != backend:
                logger.info(f"🔄 Retrying with {other_backend.url}")
                return await self.forward_request(method, path, **kwargs)
            else:
                raise HTTPException(status_code=502, detail=f"バックエンドサーバーエラー: {str(e)}")
    
    def get_status(self) -> Dict[str, Any]:
        """ロードバランサーの状態を取得"""
        backends_status = []
        for backend in self.backends:
            backends_status.append({
                "url": backend.url,
                "healthy": backend.is_healthy,
                "error_count": backend.error_count,
                "avg_response_time": round(backend.get_average_response_time(), 3),
                "last_check": backend.last_check
            })
        
        healthy_count = len([b for b in self.backends if b.is_healthy])
        
        return {
            "total_backends": len(self.backends),
            "healthy_backends": healthy_count,
            "backends": backends_status
        }

# FastAPI アプリケーション
app = FastAPI(
    title="ComeAPI Load Balancer",
    description="llama-cpp-python API用ロードバランサー",
    version="1.0.0"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# グローバル変数
load_balancer = None

@app.on_event("startup")
async def startup_event():
    """起動時の初期化"""
    await load_balancer.init_session()
    logger.info("🚀 Load Balancer started")

@app.on_event("shutdown")
async def shutdown_event():
    """終了時のクリーンアップ"""
    if load_balancer:
        await load_balancer.close_session()
    logger.info("🛑 Load Balancer stopped")

@app.get("/")
async def root():
    """ロードバランサーのステータス"""
    await load_balancer.health_check_all()
    return {"message": "ComeAPI Load Balancer", "status": load_balancer.get_status()}

@app.get("/status")
async def status():
    """詳細なステータス情報"""
    await load_balancer.health_check_all()
    return load_balancer.get_status()

@app.get("/models")
async def list_models():
    """モデル一覧 (バックエンドに転送)"""
    status, result = await load_balancer.forward_request("GET", "/models")
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

@app.post("/generate")
async def generate_text(request: Request):
    """テキスト生成 (バックエンドに転送)"""
    data = await request.json()
    status, result = await load_balancer.forward_request("POST", "/generate", json=data)
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

def create_load_balancer(host: str = "127.0.0.1", base_port: int = 8080, num_backends: int = 5) -> LoadBalancer:
    """ロードバランサーを作成"""
    backends = []
    for i in range(num_backends):
        port = base_port + i
        backend = Backend(host, port)
        backends.append(backend)
        logger.info(f"📡 Backend registered: {backend.url}")
    
    return LoadBalancer(backends)

def start_load_balancer(backend_host: str = "127.0.0.1", backend_base_port: int = 8080, 
                       num_backends: int = 5, lb_host: str = "0.0.0.0", lb_port: int = 9000):
    """ロードバランサーを起動"""
    global load_balancer
    
    print("="*60)
    print("⚖️  ComeAPI Load Balancer")
    print("="*60)
    print(f"🎯 Load Balancer: http://{lb_host}:{lb_port}")
    print(f"📡 Backend Host: {backend_host}")
    print(f"📊 Backend Ports: {backend_base_port}-{backend_base_port + num_backends - 1}")
    print(f"⚡ Total Backends: {num_backends}")
    print("="*60)
    
    load_balancer = create_load_balancer(backend_host, backend_base_port, num_backends)
    
    uvicorn.run(app, host=lb_host, port=lb_port)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("使用方法: python load_balancer.py [バックエンドホスト=127.0.0.1] [バックエンドベースポート=8080] [バックエンド数=5] [LBホスト=0.0.0.0] [LBポート=9000]")
        print("例: python load_balancer.py")
        print("例: python load_balancer.py 127.0.0.1 8080 5 0.0.0.0 9000")
        sys.exit(1)
    
    backend_host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    backend_base_port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    num_backends = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    lb_host = sys.argv[4] if len(sys.argv) > 4 else "0.0.0.0"
    lb_port = int(sys.argv[5]) if len(sys.argv) > 5 else 9000
    
    start_load_balancer(backend_host, backend_base_port, num_backends, lb_host, lb_port) 