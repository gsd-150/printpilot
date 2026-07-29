---
name: Bad_Name
description: >
  当 flow_tail_mean 越界时触发，用于验证注册期的命名规则是否真的会拒绝
  非 kebab-case 的名称与不合法的版本号。
version: 1.0
domain: fdm/test
required_inputs: [flow_tail_mean]
triggers: [flow_tail_mean]
---

# 命名与版本都不合法

名称不是 kebab-case，版本号也不是 semver。

## 排除项

无。
