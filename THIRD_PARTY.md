# 第三方组件

项目自身代码使用 MIT，第三方组件保留各自许可。

| 组件 | 用途 | 许可与来源 |
|---|---|---|
| CPython | Windows EXE 内置运行时 | PSF / [python.org](https://www.python.org/psf/license/) |
| Rich | 彩色排版、表格、动态进度 | MIT / [Textualize/rich](https://github.com/Textualize/rich) |
| python-lz4 / LZ4 | init_boot ramdisk 解压 | BSD / [python-lz4](https://github.com/python-lz4/python-lz4) |
| Requests 及依赖 | HTTPS Range 读取 | 各组件原始许可 / [Requests](https://github.com/psf/requests) |
| PyInstaller | Windows 打包与 bootloader | GPL 与 bootloader exception / [PyInstaller](https://github.com/pyinstaller/pyinstaller) |

Windows 发布包 `licenses` 保存构建时各依赖的原始许可文本。不要把项目的 MIT 许可证当作第三方组件的重新许可。

Android OTA payload 字段参考 [ssut/payload-dumper-go/update_metadata.proto](https://github.com/ssut/payload-dumper-go/blob/main/update_metadata.proto)，本项目未捆绑该工具二进制。

仓库和发布包包含官方 Windows Platform-Tools 37.0.1 的 ADB/Fastboot 最小运行集：原版程序、所需 DLL、`source.properties` 和完整 `NOTICE.txt`，不修改第三方文件。原始版权和许可证见 `platform-tools/NOTICE.txt`；本项目的 MIT 不替代它们。

固定来源、原始归档 SHA-256 和逐文件哈希见 `platform-tools/ORIGIN.json` 与 `platform-tools/SHA256SUMS.txt`，维护方法见 `platform-tools/README.md`。官方来源为 [Android Platform-Tools](https://developer.android.com/tools/releases/platform-tools)，AOSP 源码见 [ADB](https://android.googlesource.com/platform/packages/modules/adb/) 与 [system/core](https://android.googlesource.com/platform/system/core/)。KernelSU APK 和手机固件不随项目分发。

本项目是独立工具，与 Xiaomi、Google、KernelSU 官方团队无隶属关系。
