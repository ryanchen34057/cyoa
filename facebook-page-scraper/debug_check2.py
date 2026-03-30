"""檢查回應 3 的 message 和 post_id 結構"""
import re

f = open("output/debug_resp_3.json", "r", encoding="utf-8")
t = f.read()
f.close()

print("=== message 結構 (前3個) ===")
for m in list(re.finditer(r'"message":\{', t))[:3]:
    s = m.start()
    e = min(len(t), s + 500)
    print("---")
    print(t[s:e])
    print()

print("\n=== post_id 結構 (前3個) ===")
for m in list(re.finditer(r'"post_id"', t))[:3]:
    s = max(0, m.start() - 300)
    e = min(len(t), m.end() + 100)
    print("---")
    print(t[s:e])
    print()

print("\n=== creation_time 附近完整結構 (前2個) ===")
for m in list(re.finditer(r'"creation_time"', t))[:2]:
    s = max(0, m.start() - 200)
    e = min(len(t), m.end() + 800)
    print("---")
    print(t[s:e])
    print()
