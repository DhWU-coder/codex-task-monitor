"""供 JSON-RPC 客户端测试使用的最小 App Server。"""

import json
import sys
from pathlib import Path


def _send(message: dict[str, object]) -> None:
    """向标准输出写入一条 JSONL 消息。"""

    sys.stdout.write(f"{json.dumps(message)}\n")
    sys.stdout.flush()


def main() -> None:
    """读取客户端请求并返回确定的测试响应。"""

    log_path = Path(sys.argv[1])
    for raw_line in sys.stdin:
        message = json.loads(raw_line)
        method = message.get("method")
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{method}\n")
        if method == "initialize":
            _send(
                {
                    "id": message["id"],
                    "result": {
                        "userAgent": "fake-app-server",
                        "platformFamily": "unix",
                        "platformOs": "macos",
                    },
                }
            )
        elif method == "initialized":
            _send(
                {
                    "method": "thread/status/changed",
                    "params": {
                        "threadId": "thread-1",
                        "status": {"type": "active", "activeFlags": []},
                    },
                }
            )
        elif method == "thread/list":
            _send(
                {
                    "id": message["id"],
                    "result": {
                        "data": [
                            {
                                "id": "thread-1",
                                "name": "测试任务",
                                "preview": "测试任务预览",
                                "cwd": "/work/test-project",
                                "status": {"type": "active", "activeFlags": []},
                                "createdAt": 1785310000,
                                "updatedAt": 1785310100,
                                "turns": [],
                                "source": "appServer",
                            }
                        ],
                        "nextCursor": None,
                    },
                }
            )
        elif method == "never/respond":
            continue
        elif method == "large/response":
            _send(
                {
                    "id": message["id"],
                    "result": {"payload": "x" * 100_000},
                }
            )
        elif method == "exit":
            return
        elif "id" in message:
            _send({"id": message["id"], "result": {}})


if __name__ == "__main__":
    main()
