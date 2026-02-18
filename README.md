# Audio Summarizer

一个用于自动处理音视频文件并生成文字总结的Python工具。

版本：**Version 1 Hotfix 1** 的第1次修订 - 1.1.1

## 🚀 功能特点

- 🔍 **自动查找音视频文件**：递归扫描目录，支持多种音视频格式
- 🎵 **音频提取**：从视频文件中提取音频（多进程并行）
- ☁️ **OSS上传**：将音频文件上传到阿里云OSS（多进程并行）
- 📝 **语音转文字**：使用阿里云Fun-ASR API将音频转换为文字（多进程并行）
- 📊 **文字总结**：使用DeepSeek API生成文字总结（多进程并行）
- ⚡ **高性能**：支持多进程并行处理，提高处理速度
- 📋 **完整日志**：详细的处理日志和进度显示

## ✨ 1.1版本新特性
- 在github release上可以看到更详细的更新日志，这里只列出主要功能点：

### 🔄 **Checkpoint断点续传**
- 支持从上次中断处继续处理，避免重复工作
- 自动保存处理进度到`checkpoint.txt`
- 支持手动调整checkpoint值控制执行流程

### 🌐 **跨平台支持**
- 支持Windows、macOS和Linux系统
- 统一的路径处理接口，兼容不同操作系统

### 🔧 **接口标准化**
- 所有路径参数统一接受`Union[str, pathlib.Path]`类型
- 内部统一使用`pathlib.Path`对象，提高代码可维护性
- 简化主函数参数，提升代码可读性

### 📝 **增强日志系统**
- 每个类都有独立的日志标签（如`[AVFinder]`、`[AudioExtractor]`）
- 支持自定义日志文件路径
- 日志来源明确，便于调试和监控

### 🐛 **Bug修复**
- 修复音频转文字步骤中的编号错乱问题
- 修复音频提取步骤中的警告误报问题

## 📦 安装

### pip安装

```bash
pip install audio_summarizer
```

### git克隆安装

#### 1. 克隆项目

```bash
git clone https://github.com/UniBinary/audio_summarizer.git
cd audio_summarizer
```

#### 2. 安装

```bash
pip install .
```

## ⚙️ 配置

### 1. 获取API密钥和OSS配置

使用本项目需要：

1. **阿里云OSS**：
   - AccessKey ID 和 AccessKey Secret
   - OSS存储桶名称和Endpoint

2. **阿里云百炼（Fun-ASR）**：
   - API Key

3. **DeepSeek**：
   - API Key

### 2. 创建配置文件

创建JSON配置文件：

```json
{
  "bucket_name": "your-bucket-name",
  "bucket_endpoint": "your-bucket-endpoint",
  "bucket_access_key_id": "your-access-key-id",
  "bucket_access_key_secret": "your-access-key-secret",
  "funasr_api_key": "your-funasr-api-key",
  "deepseek_api_key": "your-deepseek-api-key"
}
```

## 🚀 使用方法

### 命令行方式

**以下`audiosummarizer`命令均可替换为`sumaudio`（命令别名）**

```bash
# 基本用法（使用配置文件）
audiosummarizer --input-dir /path/to/videos --output-dir /path/to/output --config-file config.json
# 或使用短别名
audiosummarizer -i /path/to/videos -o /path/to/output -c config.json

# 指定进程数
audiosummarizer --input-dir /path/to/videos --output-dir /path/to/output --processes 4 --config-file config.json
# 或使用短别名
audiosummarizer -i /path/to/videos -o /path/to/output -p 4 -c config.json

# 仅音频模式（输入目录只有音频文件）
audiosummarizer --input-dir /path/to/audios --output-dir /path/to/output --audio-only --config-file config.json
# 或使用短别名
audiosummarizer -i /path/to/audios -o /path/to/output -a -c config.json
```

### 命令行参数说明

| 长参数 | 短别名 | 是否必需 | 类型 | 默认值 | 说明 |
|--------|--------|----------|------|--------|------|
| `--config-file` | `-c` | 是 | 字符串 | 无 | 配置文件路径，包含API密钥等配置信息 |
| `--input-dir` | `-i` | 是 | 字符串 | 无 | 包含音视频文件的输入目录路径 |
| `--output-dir` | `-o` | 是 | 字符串 | 无 | 总结输出文件夹路径 |
| `--processes` | `-p` | 否 | 整数 | 1 | 同时处理的进程数 |
| `--audio-only` | `-a` | 否 | 布尔值 | False | 如果设置，则不提取视频音轨，建议在输入文件夹中只有音频时设置 |

### Python API方式

**以下Path均可使用字符串路径（接受类型为`Union[str, pathlib.Path]`）**

```python
from audiosummarizer import summarize
from pathlib import Path
from logging import getLogger

logger = getLogger("Demo")

config = {
    "bucket_name": "your-bucket-name",
    "bucket_endpoint": "your-bucket-endpoint",
    "bucket_access_key_id": "your-access-key-id",
    "bucket_access_key_secret": "your-access-key-secret",
    "funasr_api_key": "your-funasr-api-key",
    "deepseek_api_key": "your-deepseek-api-key"
}

# 使用配置文件
summarize(
    config=config,
    input_dir=Path("/path/to/videos"),
    output_dir=Path("/path/to/output"),
    processes=4, # 可选参数，指定使用的进程数，默认为1
    audio_only=False, # 可选参数，是否不提取视频中的音频，建议在输入目录只有音频文件时设置为True
    logger=logger, # 可选参数，传入自定义logger实例，如果不传入则自动创建logger
)
```

## 🔄 处理流程

项目按照以下步骤处理音视频文件：

1. **寻找音视频文件** (`AVFinder`)
   - 递归扫描输入目录
   - 支持的文件格式：`.mp3`, `.wav`, `.flac`, `.aac`, `.ogg`, `.m4a`, `.wma`, `.opus`, `.mp4`, `.avi`, `.mkv`, `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`, `.mpg`, `.mpeg`
   - 生成文件列表JSON

2. **提取音频** (`AudioExtractor`)
   - 从视频文件中提取音频轨道
   - 音频文件命名为 `001.mp3`, `002.mp3` 等（保持原顺序）
   - 多进程并行处理

3. **上传音频到OSS** (`OSSUploader`)
   - 将音频文件上传到阿里云OSS
   - 文件存储在 `oss://audios/` 目录下
   - 生成可访问的URL列表
   - 多进程并行上传

4. **音频转文字** (`AudioTranscriber`)
   - 使用阿里云Fun-ASR API进行语音识别
   - 支持说话人分离（声纹识别）
   - 输出格式：`<说话人ID>: <文本>`
   - 多进程并行处理

5. **总结文字** (`TextSummarizer`)
   - 使用DeepSeek API生成文字总结
   - 输出Markdown格式
   - 在总结开头添加原视频链接
   - 多进程并行处理

## 📁 输出文件结构

```
output_dir/
├── audio_summarizer.log          # 主日志文件
├── checkpoint.txt                # 断点续传状态文件
├── intermediates/                # 中间文件目录 
│   ├── inputs.json           # 输入文件列表
│   ├── audios.json           # 音频文件列表
│   ├── oss_urls.json         # OSS URL列表
│   ├── texts.json            # 文本文件路径列表
│   ├── summaries.json        # 总结文件路径列表
│   ├── audios/               # 提取的音频文件
│   └── texts/                # 转录的文本文件
└── summaries/                    # 最终总结文件
    ├── 001.md
    ├── 002.md
    └── ...
```

## 💰 费用估算

截止2026年2月，处理一小时音视频的估算费用：

| 服务 | 费用 | 说明 |
|------|------|------|
| 阿里云OSS | 0.014元 | 上传+读取，约100MB流量 |
| 阿里云Fun-ASR | 0.76元 | 语音识别，使用节省计划 |
| DeepSeek | 0.028元 | 文字总结 |
| **总计** | **约0.8元/小时** | |

## 🛠️ 类说明

**该项目的所有类均可以独立使用**

### AVFinder
- **功能**：查找音视频文件
- **参数**：`input_dir`, `output_json`, `logger`, `log_file`
- **方法**：`find_and_save()`
- **docstring**：
```
初始化音视频文件查找器

Args:
   input_dir: 输入目录路径，递归遍历此目录寻找音视频文件
   output_json: 输出的含有音视频文件路径列表的JSON文件路径
   logger: 日志记录器对象，若为空则自行创建
   log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
```

### AudioExtractor
- **功能**：从视频中提取音频
- **参数**：`input_json`, `output_json`, `audio_dir`, `ffmpeg_path`, `ffprobe_path`, `num_processes`, `logger`, `log_file`
- **方法**：`process_videos()`
- **docstring**：
```
初始化音频提取器

Args:
   input_json: 输入的含有音视频文件路径列表的JSON文件路径
   output_json: 输出的包含原有的音频文件和从视频中提取的音频文件的路径列表的JSON文件路径
   audio_dir: 提取后的音频存放目录路径
   ffmpeg_path: ffmpeg可执行文件路径
   ffprobe_path: ffprobe可执行文件路径
   num_processes: 并行进程数，默认为1
   logger: 日志记录器对象，若为空则自行创建
   log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
```

### OSSUploader
- **功能**：上传文件到阿里云OSS
- **参数**：`input_json`, `output_json`, `bucket_name`, `bucket_endpoint`, `access_key_id`, `access_key_secret`, `num_processes`, `logger`, `log_file`
- **方法**：`upload_files()`
- **docstring**：
```
初始化OSS上传器

Args:
   input_json: 输入的包含原有的音频文件和从视频中提取的音频文件的路径列表的JSON文件路径
   output_json: 输出的包含所有音频文件的公网URL的JSON文件路径
   bucket_name: 阿里云OSS存储桶名
   bucket_endpoint: 阿里云OSS存储桶endpoint
   access_key_id: 阿里云access key ID
   access_key_secret: 阿里云access key secret
   num_processes: 并行进程数，默认为1
   logger: 日志记录器对象，若为空则自行创建
   log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
```

### AudioTranscriber
- **功能**：音频转文字
- **参数**：`input_json`, `output_json`, `text_dir`, `model_api_key`, `num_processes`, `logger`, `log_file`
- **方法**：`transcribe_audio()`
- **docstring**：
```
初始化音频转录器

Args:
   input_json: 输入的包含所有音频文件的公网URL的JSON文件路径
   output_json: 输出的包含所有音频转写生成的文字文件的路径的JSON文件路径
   text_dir: 存放音频转写生成的文字文件的文件夹
   model_api_key: Fun-ASR模型API key
   num_processes: 并行进程数，默认为1
   logger: 日志记录器对象，若为空则自行创建
   log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
```

### TextSummarizer
- **功能**：总结文字
- **参数**：`input_json`, `output_json`, `summary_dir`, `model_api_key`, `num_processes`, `origin_json`, `logger`, `log_file`
- **方法**：`summarize_texts()`
- **docstring**：
```
初始化文本总结器

Args:
   input_json: 输入的包含所有音频转写生成的文字文件的路径的JSON文件路径
   output_json: 输出的包含所有Deepseek生成的文字总结文件的路径的JSON文件路径
   summary_dir: 存放Deepseek生成的文字总结的文件夹
   model_api_key: Deepseek模型API key
   num_processes: 并行进程数，默认为1
   origin_json: 包含每个文本文件对应的原视频路径的列表的JSON文件路径，若为空则不在生成的总结头部添加原视频路径
   logger: 日志记录器对象，若为空则自行创建
   log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
```

## ⚠️ 注意事项

1. **费用控制**：处理大量文件前，建议先测试小批量文件
2. **网络要求**：需要稳定的网络连接访问OSS和API
3. **文件大小**：单个音频文件时长不能超过12小时，大小不能超过2GB，请分割长音频。
4. **API限制**：注意各API的调用频率和并发限制，合理设置进程数
5. **隐私保护**：音频内容可能包含敏感信息，请妥善处理
6. **断点续传**：不要手动删除`checkpoint.txt`和中间目录，否则无法继续处理

## 🔧 故障排除

### 常见问题

1. **导入错误**：确保已安装所有依赖 `pip install oss2 dashscope openai`
2. **OSS连接失败**：检查AccessKey和Endpoint配置
3. **API调用失败**：检查API密钥和网络连接
4. **ffmpeg错误**：确保 `ffmpeg.exe` 和 `ffprobe.exe` 在正确位置
5. **断点续传失败**：检查`checkpoint.txt`文件是否损坏，或中间目录是否被删除

### 日志查看

发生错误时，请查看日志文件获取详细错误信息：`output_dir/audio_summarizer.log`

## 📄 许可证

MIT License

## 👤 作者

UniBinary - tp114514251@outlook.com

## 🌐 项目网址

GitHub: https://github.com/UniBinary/audio_summarizer
