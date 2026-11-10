"""빠른 실행용 엔트리포인트 (PyInstaller 로 RemoteDesktopHost.exe 를 만들 때 사용).

    python run_host.py
"""
from agent.host_app import main

if __name__ == "__main__":
    main()
