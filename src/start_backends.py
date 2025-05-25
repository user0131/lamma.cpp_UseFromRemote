#!/usr/bin/env python3
"""
複数のバックエンドサーバーを起動するスクリプト
ロードバランサー用に5つのサーバーインスタンスを異なるポートで起動
"""

import os
import sys
import subprocess
import time
import signal
from typing import List

class BackendManager:
    def __init__(self, models_dir: str, host: str = "127.0.0.1", base_port: int = 8070, num_backends: int = 5):
        self.models_dir = models_dir
        self.host = host
        self.base_port = base_port
        self.num_backends = num_backends
        self.processes: List[subprocess.Popen] = []
        
    def start_backends(self):
        """全てのバックエンドサーバーを起動"""
        print(f"🚀 {self.num_backends}個のバックエンドサーバーを起動中...")
        
        for i in range(self.num_backends):
            port = self.base_port + i
            self._start_backend(port, i + 1)
            time.sleep(2)  # 起動間隔を空ける
            
        print(f"✅ 全{self.num_backends}個のバックエンドサーバーが起動しました")
        self._print_status()
        
    def _start_backend(self, port: int, instance_num: int):
        """単一のバックエンドサーバーを起動"""
        print(f"📡 Backend {instance_num}: ポート {port} で起動中...")
        
        # スクリプトの場所を基準にbackend_server.pyのパスを決定
        script_dir = os.path.dirname(os.path.abspath(__file__))
        backend_script = os.path.join(script_dir, "backend_server.py")
        
        cmd = [
            sys.executable, backend_script,
            self.models_dir,
            self.host,
            str(port),
            "1"  # 1スレッドで安定動作
        ]
        
        try:
            # ログ出力を無効化（長期間実行でもログが蓄積しない）
            with open(os.devnull, 'w') as devnull:
                process = subprocess.Popen(
                    cmd,
                    stdout=devnull,
                    stderr=devnull,
                    preexec_fn=os.setsid if hasattr(os, 'setsid') else None
                )
            self.processes.append(process)
            print(f"✅ Backend {instance_num}: PID {process.pid}")
            
        except Exception as e:
            print(f"❌ Backend {instance_num} の起動に失敗: {e}")
            
    def _print_status(self):
        """起動状況を表示"""
        print("\n" + "="*60)
        print("📊 バックエンドサーバー状況:")
        print("="*60)
        for i, process in enumerate(self.processes):
            port = self.base_port + i
            if process.poll() is None:
                print(f"🟢 Backend {i+1}: http://{self.host}:{port} (PID: {process.pid})")
            else:
                print(f"🔴 Backend {i+1}: http://{self.host}:{port} (停止)")
        print("="*60)
        print("🛑 停止するには Ctrl+C を押してください")
        print("="*60 + "\n")
        
    def stop_backends(self):
        """全てのバックエンドサーバーを停止"""
        print("\n🛑 バックエンドサーバーを停止中...")
        
        for i, process in enumerate(self.processes):
            if process.poll() is None:
                try:
                    # グループ全体にSIGTERMを送信
                    if hasattr(os, 'killpg'):
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    else:
                        process.terminate()
                    print(f"✅ Backend {i+1} を停止しました")
                except Exception as e:
                    print(f"⚠️  Backend {i+1} の停止中にエラー: {e}")
                    
        # プロセスの終了を待機
        for process in self.processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                
        print("✅ 全てのバックエンドサーバーが停止しました")
        
    def wait(self):
        """全てのプロセスが終了するまで待機"""
        try:
            while True:
                time.sleep(1)
                # 全プロセスが終了したかチェック
                if all(process.poll() is not None for process in self.processes):
                    print("⚠️  全てのバックエンドサーバーが予期せず停止しました")
                    break
        except KeyboardInterrupt:
            self.stop_backends()

def main():
    if len(sys.argv) < 2:
        print("使用方法: python start_backends.py <モデルディレクトリ> [ホスト=127.0.0.1] [ベースポート=8070] [バックエンド数=5]")
        print("例: python start_backends.py ./models")
        print("例: python start_backends.py ./models 0.0.0.0 8070 5")
        print("例: python start_backends.py ./models 127.0.0.1 8070 30  # 最大30台並列")
        sys.exit(1)
        
    models_dir = sys.argv[1]
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    base_port = int(sys.argv[3]) if len(sys.argv) > 3 else 8070
    num_backends = int(sys.argv[4]) if len(sys.argv) > 4 else 5
    
    # バックエンド数の制限チェック
    if num_backends > 30:
        print(f"❌ エラー: バックエンド数は最大30台です: {num_backends}")
        sys.exit(1)
    
    # ポート範囲チェック（8070-8099）
    if base_port < 8070 or base_port + num_backends > 8100:
        print(f"❌ エラー: ポート範囲は8070-8099です: {base_port}-{base_port + num_backends - 1}")
        sys.exit(1)
    
    # モデルディレクトリの確認
    if not os.path.isdir(models_dir):
        print(f"❌ エラー: モデルディレクトリが存在しません: {models_dir}")
        sys.exit(1)
        
    # メモリ使用量の警告
    if num_backends > 10:
        estimated_memory = num_backends * 2.3  # Qwen3-4B per backend
        if num_backends == 30:
            print(f"🖥️  Mac Studio構成: {num_backends}台のバックエンドで約{estimated_memory:.1f}GBのメモリが必要です")
            print("   Mac Studio 512GBメモリで最適化された構成です")
        elif estimated_memory > 32:
            print(f"⚠️  警告: {num_backends}台のバックエンドで約{estimated_memory:.1f}GBのメモリが必要です")
            print("   64GB以上のメモリを推奨します")
        else:
            print(f"📊 メモリ使用量: {num_backends}台で約{estimated_memory:.1f}GB（32GB環境で快適）")
        
    print("="*60)
    print("🎯 ComeAPI ロードバランサー システム")
    print("="*60)
    print(f"📁 モデルディレクトリ: {models_dir}")
    print(f"🌐 ホスト: {host}")
    print(f"🔢 ベースポート: {base_port}")
    print(f"⚡ バックエンド数: {num_backends}")
    print(f"📊 ポート範囲: {base_port}-{base_port + num_backends - 1}")
    if num_backends <= 10:
        print(f"💾 推定メモリ使用量: 約{num_backends * 2.3:.1f}GB")
    print("="*60)
    
    manager = BackendManager(models_dir, host, base_port, num_backends)
    manager.start_backends()
    manager.wait()

if __name__ == "__main__":
    main() 