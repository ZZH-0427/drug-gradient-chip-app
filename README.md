# Android binary-only release metadata

本分支 `release/android-binary` 仅用于“智能药物浓度预测平台”Android 二进制发布记录。

Git 树只包含 `README.md` 与 `release-manifest.json`，不包含 Android 源码、APK、独立模型、实验 JSON、科研文件或构建缓存。

附注标签 `v0.4.0-rc1` 是 **binary-only release metadata tag**，指向本仓库新创建的无父提交元数据根提交。它不指向 Windows master 或原始 Android 开发提交，也不表示 GitHub 已托管完整 Android 源码。

APK 作为未来 Release 的独立二进制附件处理；文件名、字节数、SHA256、Debug 签名及测试版状态见清单。此处的源码来源字段只作历史追溯，不构成 Git 父子关系或可复现构建证明。

当前仅完成本地准备；未配置远程、未同步或创建 GitHub Release。
