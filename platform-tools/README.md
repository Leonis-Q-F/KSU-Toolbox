# Bundled Platform-Tools

Windows ADB/Fastboot 37.0.1, copied without modification from the pinned Google archive.

Source: https://dl.google.com/android/repository/platform-tools_r37.0.1-win.zip

Archive SHA-256: `45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99`

The repository and release packages contain only ADB, Fastboot, their runtime DLLs, source.properties and the complete original NOTICE.txt. These components retain their original licenses; the project MIT license does not replace them.

See NOTICE.txt for original copyrights and license terms. AOSP sources: https://android.googlesource.com/platform/packages/modules/adb/ and https://android.googlesource.com/platform/system/core/ .

Maintainers can reproduce this directory with `python tools/platform_tools.py --archive PATH_TO_OFFICIAL_ZIP`. Without --archive the script fetches the pinned URL and checks the archive hash before writing. Normal tool startup and release builds do not download SDKs.
