#!/usr/bin/env python3
"""本地 HTTP 探活：2xx 返回 0，其余返回 1。绕过 HTTP_PROXY，等价 curl --noproxy '*'。

用法：python3 http_ok.py http://127.0.0.1:9292/health
"""
import sys
import urllib.request

url = sys.argv[1]
# 显式清空代理：集群镜像通常带 HTTP_PROXY，localhost 探测不能走代理
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(url, timeout=3) as r:
        code = r.getcode()
    sys.exit(0 if code and 200 <= code < 300 else 1)
except Exception:
    sys.exit(1)
