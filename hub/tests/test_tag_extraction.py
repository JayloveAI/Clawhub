# -*- coding: utf-8 -*-
"""Tag Extraction V2.0 Tests"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client_sdk.utils.tag_utils import (
    extract_multilingual_tokens,
    extract_and_clean,
    clean_extract_tags,
    CHINESE_STOPWORDS,
    EN_STOPWORDS,
)

PASSED = 0
FAILED = 0

def test(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {name}")
    else:
        FAILED += 1
        print(f"  FAIL: {name} {detail}")


# === 1. Garbage Chinese tags regression ===
print("\n=== 1. Garbage Tags Regression ===")
# Old system produced "均失败", "当前使用", "需要获取题为" as single tags.
# New system segments them, and each part should be either filtered or meaningful.
# Key: none of these garbage phrases should pass through as-is.
garbage_phrases = [
    "\u5747\u5931\u8d25",       # jun shi bai - "均失败"
    "\u5f53\u524d\u4f7f\u7528", # dang qian shi yong - "当前使用"
    "\u9700\u8981\u83b7\u53d6\u9898\u4e3a", # xu yao huo qu ti wei - "需要获取题为"
    "\u6574\u5168\u6587\u5185\u5bb9",       # zheng quan wen nei rong - "整全文内容"
    "\u8fd9\u7bc7\u62a5\u544a\u7684\u5b8c", # zhe pian bao gao de wan
]
for g in garbage_phrases:
    r = extract_multilingual_tokens(g)
    # The garbage phrase itself must NOT appear in output as a single tag
    test(f'no "{g}" as single tag', g not in r, f"still present: {r}")
    # After segmentation, remaining tokens should be very few or empty
    for t in r:
        # Each remaining token should not be a known stopword
        test(f'  token "{t}" not stopword', t not in CHINESE_STOPWORDS and t not in EN_STOPWORDS, "still stopword")


# === 2. English stopwords ===
print("\n=== 2. English Stopwords ===")
r = extract_multilingual_tokens("the content of this data info")
test("all-english-stopwords", r == [], f"got {r}")
r2 = extract_multilingual_tokens("THIS AND THAT OR THE DATA INFO")
test("uppercase-stopwords", r2 == [], f"got {r2}")


# === 3. Real demand test ===
print("\n=== 3. Real Demand (fa78a1c2) ===")
real_demand = '\u9700\u8981\u83b7\u53d6\u9898\u4e3a\u300aClaude Code Harness\uff1a\u4ece\u9006\u5411\u5de5\u7a0b\u5230\u4ea7\u54c1\u539f\u7406\u5b8c\u6574\u8fd8\u539f\u3000\u7684\u5168\u6587\u5185\u5bb9...'
r = extract_multilingual_tokens(real_demand)
test("claude present", "claude" in r, f"got {r}")
test("code present", "code" in r, f"got {r}")
test("harness present", "harness" in r, f"got {r}")
test("no garbage jun shi bai", "\u5747\u5931\u8d25" not in r)
test("no dang qian shi yong", "\u5f53\u524d\u4f7f\u7528" not in r)
test("no xu yao huo qu ti wei", "\u9700\u8981\u83b7\u53d6\u9898\u4e3a" not in r)


# === 4. Meaningful Chinese extraction ===
print("\n=== 4. Meaningful Chinese ===")
cn_text = "\u534e\u521b\u8bc1\u5238\u52a8\u529b\u7164\u7814\u7a76\u62a5\u544a"
r = extract_multilingual_tokens(cn_text)
test("has meaningful tokens", len(r) > 0, f"got {r}")
# jieba should segment into meaningful words, not garbage
has_good = any(len(t) >= 2 for t in r)
test("has multi-char tokens", has_good, f"got {r}")


# === 5. Case normalization ===
print("\n=== 5. Case Normalization ===")
r = extract_multilingual_tokens("CLAUDE Code HARNESS")
test("all lowercase", all(t == t.lower() for t in r), f"got {r}")
test("claude present", "claude" in r)
test("code present", "code" in r)
test("harness present", "harness" in r)


# === 6. Cross-language alignment ===
print("\n=== 6. Cross-Language Alignment ===")
en = extract_multilingual_tokens("reverse engineering analysis")
cn = extract_multilingual_tokens("\u9006\u5411\u5de5\u7a0b\u5206\u6790")
test("EN has tokens", len(en) > 0, f"got {en}")
test("CN has tokens", len(cn) > 0, f"got {cn}")
test("EN no garbage", "analysis" in en or "engineering" in en, f"got {en}")


# === 7. Edge cases ===
print("\n=== 7. Edge Cases ===")
test("empty string", extract_multilingual_tokens("") == [])
test("none input", extract_multilingual_tokens(None) == [])
test("pure numbers", extract_multilingual_tokens("12345") == [])
test("single char", extract_multilingual_tokens("a") == [])


# === 8. API backward compatibility ===
print("\n=== 8. API Compatibility ===")
tags = clean_extract_tags(["sdk", "api", "\u9700\u8981", "\u83b7\u53d6", "file"])
test("sdk kept", "sdk" in tags)
test("api kept", "api" in tags)
test("file kept", "file" in tags)
test("stopword removed", "\u9700\u8981" not in tags)

ec = extract_and_clean("\u9700\u8981\u83b7\u53d6\u300aClaude Code Harness\u300b\u62a5\u544a\u7684\u5b8c\u6574\u5185\u5bb9")
test("extract_and_clean works", isinstance(ec, list))
test("has claude", "claude" in ec, f"got {ec}")


# === Summary ===
print(f"\n{'='*50}")
print(f"Results: {PASSED} passed, {FAILED} failed")
if FAILED > 0:
    sys.exit(1)
print("ALL TESTS PASSED")
