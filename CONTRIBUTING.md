# 参与开发

Python 3.10+，Windows x64。先安装 `requirements-dev.txt`，然后运行：

```cmd
python -m unittest discover -s tests -v
python src\cli.py --menu
python src\cli.py --plain --type ota --check "当前版本完整包.zip"
```

提交应说明具体问题、结果和测试证据。界面改动提供真实渲染图；固件解析或刷写边界变更需要包含失败场景的回归测试。

测试默认使用生成的合成镜像和模拟 USB，不应连接或刷写真实手机。真实镜像测试可通过本机环境变量 `KSU_TEST_STOCK_IMAGE`、`KSU_TEST_PATCH_IMAGE`、`KSU_TEST_V331_PATCH_IMAGE` 指定，未配置时跳过，不提交样本。

不要提交固件、APK、私有下载链接、序列号、用户目录、`sessions` 或凭据。第三方程序只允许提交 `platform-tools` 中固定清单与校验记录覆盖的官方最小运行集，其他二进制不应加入仓库。Issue 日志分享前须脱敏；完整备份和 `session.json` 不应直接上传。

项目代码使用 MIT 许可证。第三方依赖保留自身许可证。新机型和修补布局只有在版本核对、恢复路径和回归测试充分时才扩展支持范围。
