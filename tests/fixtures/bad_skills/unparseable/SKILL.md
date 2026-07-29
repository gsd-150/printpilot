---
name: unparseable
description: "未闭合的引号导致 YAML 解析失败
version: 0.1.0
	domain: 制表符缩进
---

# 存在的意义是被 R0 拦下

前面的 frontmatter 无法被解析为 YAML。校验工具遇到它必须**报告**而不是崩溃——
崩溃会让同一次运行中其余 Skill 的问题全部被掩盖。

## 排除项

无。
