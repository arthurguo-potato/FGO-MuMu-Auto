# 离线依赖缓存

正式发布包会把这里的Windows 64位轮子复制到根目录 `wheels/`，供首次启动离线安装。
二进制轮子默认不提交Git；缺失时运行 `scripts/prepare_wheelhouse.ps1` 重新下载并校验。

支持CPython 3.10、3.11和3.12。`SHA256SUMS.txt` 中的值来自对应版本的PyPI官方文件页。
