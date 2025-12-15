import subprocess
import time
import os
import signal
import sys

# 进程列表，用于统一关闭
processes = []


def start_process(command, name):
    print(f"🚀 Starting {name}...")
    # Windows 和 Linux 的 Popen 处理稍有不同
    if os.name == 'nt':
        # Windows
        p = subprocess.Popen(command, shell=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        # Linux/Mac
        p = subprocess.Popen(command, shell=True, preexec_fn=os.setsid)
    return p


def signal_handler(sig, frame):
    print("\n🛑 Shutting down all services...")
    for p in processes:
        if os.name == 'nt':
            # Windows Kill
            subprocess.call(['taskkill', '/F', '/T', '/PID', str(p.pid)])
        else:
            # Linux Kill Group
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    sys.exit(0)


def main():
    # 注册 Ctrl+C 信号
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 1. 启动 DB Writer (数据库写入守护进程)
        # 确保 python 路径正确，如果是虚拟环境可能需要指定 full path
        p_writer = start_process("python -m services.db_writer", "DB Writer Daemon")
        processes.append(p_writer)
        time.sleep(1)

        # 2. 启动 Celery Worker (核心执行器)
        # 【重要变化】使用 threads 模式，并发数 50
        # -P threads: 使用线程池 (兼容 requests/msal)
        # -c 50: 开启 50 个线程
        # -l info: 日志级别
        if os.name == 'nt':
            # Windows 对 -P threads 支持很好，或者用 solo (单线程调试)
            # 这里为了性能用 threads
            cmd_worker = "celery -A celery_app worker --pool=threads --concurrency=50 --loglevel=info"
        else:
            cmd_worker = "celery -A celery_app worker --pool=threads --concurrency=50 --loglevel=info"

        p_worker = start_process(cmd_worker, "Celery Worker")
        processes.append(p_worker)

        # 3. 启动 Celery Beat (定时任务调度器)
        p_beat = start_process("celery -A celery_app beat --loglevel=info", "Celery Beat")
        processes.append(p_beat)

        # 4. 启动 FastAPI
        p_api = start_process("uvicorn app:app --host 0.0.0.0 --port 8000 --reload", "FastAPI Server")
        processes.append(p_api)

        print("\n✅ System matches configured! (Mode: Threads, Concurrency: 50)")
        print("Press Ctrl+C to stop.\n")

        # 阻塞主线程，监控子进程
        while True:
            time.sleep(1)
            # 可以在这里加简单的健康检查逻辑

    except Exception as e:
        print(f"Error: {e}")
        signal_handler(None, None)


if __name__ == "__main__":
    main()