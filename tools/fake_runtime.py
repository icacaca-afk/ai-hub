#!/usr/bin/env python3
"""Stub Provider 的"假 Runtime"。

不依赖 shell，直接被 Python subprocess 调用。
用法：python fake_runtime.py <task>
输出：将 <task> 包装为 "Stub processed: <task>"
"""
import sys

if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    print(f"Stub processed: {task}")
    sys.exit(0)
