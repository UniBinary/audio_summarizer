# Audio Summarizer 更新说明
- 上个版本：**Version 1 Subversion 1 Hotfix 1** - 1.1.1
- 现版本：**Version 1 Subversion 2** - 1.2
- 该包已发布至同名PyPI项目

## 1. 功能增强

### 命令行参数增强
- 上个版本：命令行参数只有长格式，使用不便。
- 现版本：为所有主要命令行参数添加短别名，提升用户体验：
  - `--config-file` → `-c`
  - `--input-dir` → `-i`
  - `--output-dir` → `-o`
  - `--processes` → `-p`
  - `--audio-only` → `-a`
  - `--log-level` → `-l`

### 日志系统增强
- 上个版本：日志级别固定，无法动态调整。
- 现版本：添加 `--log-level` 参数支持，用户可以在运行时指定日志级别（debug/info/warning/error/critical）。

### 文件过滤功能
- 上个版本：无法过滤过大或过长的音视频文件。
- 现版本：`AVFinder` 类新增 `size_limit` 和 `duration_limit` 参数，支持按文件大小和时长过滤音视频文件。

### 音频提取失败处理优化
- 上个版本：当所有音频提取失败时，程序仍会继续执行后续步骤，可能导致错误。
- 现版本：优化音频提取失败处理逻辑，当所有音频提取失败时，`AudioExtractor.process_videos()`方法会返回`False`，程序会提前终止并给出明确错误提示。

### OSS上传优化
- 上个版本：每次运行都会重新上传所有文件，即使文件已存在。
- 现版本：`OSSUploader` 类新增 `skip_exists` 参数，支持跳过已存在的OSS文件，减少不必要的上传。

### 文本总结优化
- 上个版本：每次运行都会重新生成所有文本总结，即使总结文件已存在。
- 现版本：`TextSummarizer` 类新增文件跳过逻辑，如果总结文件已存在且内容有效，则跳过该文件的总结过程。

## 2. 接口改进

### 配置键名标准化
- 上个版本：OSS配置键名不一致，使用 `bucket_access_key_id` 和 `bucket_access_key_secret`。
- 现版本：统一OSS配置键名为 `aliyun_access_key_id` 和 `aliyun_access_key_secret`，提高配置一致性。

### Logger接口改进
- 上个版本：类构造函数直接接受logger实例，导致logger配置复杂。
- 现版本：所有类改为接受 `logger_suffix` 参数，内部自动创建带标签的logger，简化logger配置。

### 参数验证增强
- 上个版本：输入JSON中的空字符串路径可能导致错误。
- 现版本：`AudioExtractor` 类添加空字符串路径过滤，自动跳过无效路径。

## 3. 跨平台兼容性

### 跨平台路径查找优化
- 上个版本：ffprobe可执行文件路径查找逻辑中包含硬编码的Windows路径和`.exe`扩展名。
- 现版本：优化ffprobe路径查找逻辑，根据当前操作系统平台动态选择正确的可执行文件名和常见安装路径：
  - **Windows**: 支持 `.exe` 扩展名和常见安装路径
  - **macOS**: 支持Homebrew安装路径 (`/usr/local/bin`, `/opt/homebrew/bin`)
  - **Linux**: 支持标准Unix路径 (`/usr/bin`, `/usr/local/bin`)

## 4. Bug修复

### 跨平台兼容性修复
- 修复了 `AVFinder._get_file_duration()` 方法中的ffprobe路径查找逻辑。
- 修复了 `AudioExtractor._get_duration()` 方法中的ffprobe路径查找逻辑。

### 音频提取错误处理修复
- 修复了当所有音频文件提取失败时，程序仍会继续执行的问题。

### 子进程日志修复
- 修复了在多进程环境下子进程logger配置问题，确保子进程也能正确记录日志。

### 文件验证修复
- 改进了 `AudioExtractor._check_audio_correct()` 方法的日志输出，提供更详细的验证信息。

## 5. 性能优化

### 减少重复工作
- OSS上传支持跳过已存在的文件
- 文本总结支持跳过已存在的总结文件
- 音频提取支持验证已存在的音频文件正确性

### 内存优化
- 改进空字符串路径过滤，减少无效数据处理
- 优化文件列表加载和验证逻辑