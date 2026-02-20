# 修改记录

## 2026-02-20: 跨平台兼容性修复

### 修改内容
修复了`audiosummarizer/utils.py`文件中不符合跨平台原则的代码，特别是硬编码的Windows可执行文件扩展名和路径。

### 具体修改

#### 1. 修复 `_get_file_duration` 方法中的ffprobe路径查找
**修改前:**
```python
possible_paths = [
    Path("ffprobe.exe"),
    Path("ffprobe"),
    Path(r"C:\ffmpeg\bin\ffprobe.exe"),
    Path(r"C:\Program Files\ffmpeg\bin\ffprobe.exe"),
    Path(r"D:\ffmpeg\bin\ffprobe.exe"),
]
```

**修改后:**
```python
possible_paths = []
possible_paths.append(Path("ffprobe"))

if sys.platform == "win32":
    possible_paths.append(Path("ffprobe.exe"))

common_paths = []
if sys.platform == "win32":
    common_paths = [
        Path(r"C:\ffmpeg\bin\ffprobe.exe"),
        Path(r"C:\Program Files\ffmpeg\bin\ffprobe.exe"),
        Path(r"D:\ffmpeg\bin\ffprobe.exe"),
    ]
elif sys.platform == "darwin":
    common_paths = [
        Path("/usr/local/bin/ffprobe"),
        Path("/opt/homebrew/bin/ffprobe"),
    ]
else:
    common_paths = [
        Path("/usr/bin/ffprobe"),
        Path("/usr/local/bin/ffprobe"),
    ]

possible_paths.extend(common_paths)
```

#### 2. 修复 `_get_duration` 方法中的ffprobe路径查找
**修改前:**
```python
ffprobe_path = self.ffmpeg_path.parent / "ffprobe.exe"
if not ffprobe_path.exists():
    ffprobe_path = self.ffmpeg_path.with_name("ffprobe.exe")
```

**修改后:**
```python
ffprobe_path = None
possible_names = ["ffprobe"]
if sys.platform == "win32":
    possible_names.append("ffprobe.exe")

for name in possible_names:
    test_path = self.ffmpeg_path.parent / name
    if test_path.exists():
        ffprobe_path = test_path
        break
    
    test_path = self.ffmpeg_path.with_name(name)
    if test_path.exists():
        ffprobe_path = test_path
        break

if ffprobe_path is None:
    ffprobe_path = Path("ffprobe")
```

### 跨平台支持
- **Windows**: 支持 `.exe` 扩展名和Windows特定路径
- **macOS**: 支持Homebrew安装路径 (`/usr/local/bin`, `/opt/homebrew/bin`)
- **Linux/Unix**: 支持标准Unix路径 (`/usr/bin`, `/usr/local/bin`)

### 影响
- 代码现在可以在Windows、macOS和Linux上正确运行
- ffprobe可执行文件的查找逻辑现在是平台感知的
- 移除了硬编码的Windows特定假设，提高了代码的可移植性

## 2026-02-20: 修改AudioExtractor类的process_videos()方法

### 修改内容
修改了`audiosummarizer/utils.py`文件中的`AudioExtractor.process_videos()`方法，当所有音频都提取失败时返回False。

### 具体修改
在`process_videos()`方法的最后部分，添加了以下检查逻辑：

```python
# 检查是否所有音频都提取失败
if self.success_count == 0 and self.failed_count > 0:
    self.logger.error("所有音频提取都失败了！")
    return False
```

### 逻辑说明
- 当`success_count == 0`且`failed_count > 0`时，表示所有音频提取都失败了，返回False
- 其他情况（包括有成功提取、全部跳过、或没有文件）都返回True

### 测试用例
1. **所有音频提取失败**：返回False
2. **部分成功，部分失败**：返回True（因为有成功提取）
3. **所有文件都是音频文件（全部跳过）**：返回True
4. **混合情况：跳过和成功**：返回True
5. **混合情况：跳过和失败**：返回False（因为没有成功提取）
6. **没有文件**：返回True（边缘情况）

### 影响
- 当所有音频提取失败时，`process_videos()`会返回False
- 在`main.py`中，这会触发错误日志"提取音频失败"并退出程序
- 这提供了更好的错误处理，避免了在完全没有音频的情况下继续执行后续步骤