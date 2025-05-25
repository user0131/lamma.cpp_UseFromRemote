import asyncio
import aiohttp
import time
import logging
import sys
from typing import List, Dict, Any, Optional, Tuple
from contextlib import asynccontextmanager
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
        self.response_times.append(response_time)
        # 最新10件のみ保持
        if len(self.response_times) > 10:
            self.response_times.pop(0)
    
    def get_average_response_time(self) -> float:
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)
    
    def mark_error(self):
        self.error_count += 1
        if self.error_count >= 3:
            self.is_healthy = False
    
    def mark_success(self):
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
        if self.session is None:
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=20)
            timeout = aiohttp.ClientTimeout(total=120)
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    
    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    async def health_check(self, backend: Backend) -> bool:
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
        current_time = time.time()
        tasks = []
        
        for backend in self.backends:
            # 30秒ごとにヘルスチェック
            if current_time - backend.last_check > 30:
                tasks.append(self.health_check(backend))
            
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def get_next_backend(self) -> Optional[Backend]:
        healthy_backends = [b for b in self.backends if b.is_healthy]
        
        if not healthy_backends:
            return None
            
        # ラウンドロビン方式
        backend = healthy_backends[self.current_index % len(healthy_backends)]
        self.current_index = (self.current_index + 1) % len(healthy_backends)
        
        return backend
    
    async def forward_request(self, method: str, path: str, **kwargs) -> Tuple[int, Dict[str, Any]]:
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

# グローバル変数
load_balancer = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時
    await load_balancer.init_session()
    logger.info("Load Balancer started")
    yield
    # 終了時
    if load_balancer:
        await load_balancer.close_session()
    logger.info("Load Balancer stopped")

# FastAPI アプリケーション
app = FastAPI(
    title="LlamaAPI Load Balancer",
    description="llama-cpp-python API用ロードバランサー",
    version="1.0.0",
    lifespan=lifespan
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    await load_balancer.health_check_all()
    return {"message": "LlamaAPI Load Balancer", "status": load_balancer.get_status()}

@app.get("/status")
async def status():
    await load_balancer.health_check_all()
    return load_balancer.get_status()

# OpenAI API互換エンドポイント
@app.get("/v1")
async def v1_root():
    await load_balancer.health_check_all()
    return {
        "object": "api",
        "version": "v1",
        "message": "LlamaAPI Load Balancer - OpenAI Compatible",
        "status": load_balancer.get_status()
    }

@app.get("/v1/models")
async def v1_list_models():
    status, result = await load_balancer.forward_request("GET", "/v1/models")
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    
    return result

@app.post("/v1/chat/completions")
async def v1_chat_completions(request: Request):
    data = await request.json()
    
    # バックエンドの/v1/chat/completionsに直接転送
    status, result = await load_balancer.forward_request("POST", "/v1/chat/completions", json=data)
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    
    return result

@app.post("/v1/beta/chat/completions/parse")
async def v1_beta_chat_completions_parse(request: Request):
    data = await request.json()
    
    # バックエンドのbeta.chat.completions.parseエンドポイントに直接転送
    status, result = await load_balancer.forward_request("POST", "/v1/beta/chat/completions/parse", json=data)
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    
    return result

def create_load_balancer(host: str = "127.0.0.1", base_port: int = 8080, num_backends: int = 5) -> LoadBalancer:
    backends = []
    for i in range(num_backends):
        port = base_port + i
        backend = Backend(host, port)
        backends.append(backend)
        logger.info(f"📡 Backend registered: {backend.url}")
    
    return LoadBalancer(backends)

def start_load_balancer(backend_host: str = "127.0.0.1", backend_base_port: int = 8080, 
                       num_backends: int = 5, lb_host: str = "0.0.0.0", lb_port: int = 9000):
    global load_balancer
    
    print("="*60)
    print("⚖️  LlamaAPI Load Balancer")
    print("="*60)
    print(f"🎯 Load Balancer: http://{lb_host}:{lb_port}")
    print(f"📡 Backend Host: {backend_host}")
    print(f"📊 Backend Ports: {backend_base_port}-{backend_base_port + num_backends - 1}")
    print(f"⚡ Total Backends: {num_backends}")
    print("="*60)
    
    load_balancer = create_load_balancer(backend_host, backend_base_port, num_backends)
    
    uvicorn.run(app, host=lb_host, port=lb_port)

def main():
    if len(sys.argv) < 4:
        print("使用方法: python load_balancer.py <バックエンドホスト> <ベースポート> <バックエンド数> [LBホスト=0.0.0.0] [LBポート=9000]")
        print("例: python load_balancer.py 127.0.0.1 8070 30 0.0.0.0 9000  # 30台並列")
        sys.exit(1)
    
    backend_host = sys.argv[1]
    backend_base_port = int(sys.argv[2])
    num_backends = int(sys.argv[3])
    lb_host = sys.argv[4] if len(sys.argv) > 4 else "0.0.0.0"
    lb_port = int(sys.argv[5]) if len(sys.argv) > 5 else 9000
    
    # バックエンド数の制限チェック
    if num_backends > 30:
        print(f"❌ エラー: バックエンド数は最大30台です: {num_backends}")
        sys.exit(1)
    
    # ポート範囲チェック（8070-8099）
    if backend_base_port < 8070 or backend_base_port + num_backends > 8100:
        print(f"❌ エラー: バックエンドポート範囲は8070-8099です: {backend_base_port}-{backend_base_port + num_backends - 1}")
        sys.exit(1)
    
    start_load_balancer(backend_host, backend_base_port, num_backends, lb_host, lb_port)

if __name__ == "__main__":
    main() 