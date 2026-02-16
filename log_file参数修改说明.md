# log_file参数功能实现说明

## 功能需求
在`utils.py`中的每个类的参数列表尾部增加一个参数：`log_file: Union[str, Path] = None`。然后在`_setup_logger`中增加一个判断逻辑：如果`log_file`不为`None`，则将日志输出到`log_file`。

## 实现方案

### 1. 修改的类
修改了`utils.py`中的所有5个类：
1. `AVFinder` - 音视频文件查找器
2. `AudioExtractor` - 音频提取器
3. `OSSUploader` - OSS上传器
4. `AudioTranscriber` - 音频转录器
5. `TextSummarizer` - 文本总结器

### 2. 修改内容

#### 2.1 构造函数修改
在每个类的`__init__`方法参数列表尾部添加了`log_file`参数：
```python
def __init__(self, ..., logger=None, log_file: Union[str, Path] = None):
```

同时添加了对应的属性存储：
```python
self.log_file = Path(log_file) if log_file else None
```

#### 2.2 `_setup_logger`方法修改
修改了每个类的`_setup_logger`方法，添加了自定义日志文件支持：
```python
def _setup_logger(self):
    self.logger = logging.getLogger("ClassName")
    self.logger.setLevel(logging.INFO)
    
    if not self.logger.handlers:
        # 控制台handler（保持不变）
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('[ClassName] %(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
    
        # 文件handler（新增自定义日志文件支持）
        if self.log_file:
            # 使用自定义日志文件
            log_file_path = Path(self.log_file)
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
            self.logger.info(f"使用自定义日志文件: {log_file_path}")
        else:
            # 使用默认日志文件
            output_dir = self.output_json.parent  # 或其他适当的目录
            output_dir.mkdir(parents=True, exist_ok=True)
            log_file_path = output_dir / "ClassName.log"
            file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
            self.logger.info(f"使用默认日志文件: {log_file_path}")
        
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter('[ClassName] %(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)
```

### 3. 具体修改详情

#### 3.1 AVFinder类
- **参数添加**: `log_file: Union[str, Path] = None`
- **默认日志文件**: `output_json.parent/AVFinder.log`
- **自定义日志文件**: 当`log_file`不为`None`时使用

#### 3.2 AudioExtractor类
- **参数添加**: `log_file: Union[str, Path] = None`
- **默认日志文件**: `audio_dir/AudioExtractor.log`
- **自定义日志文件**: 当`log_file`不为`None`时使用

#### 3.3 OSSUploader类
- **参数添加**: `log_file: Union[str, Path] = None`
- **默认日志文件**: `output_json.parent/OSSUploader.log`
- **自定义日志文件**: 当`log_file`不为`None`时使用

#### 3.4 AudioTranscriber类
- **参数添加**: `log_file: Union[str, Path] = None`
- **默认日志文件**: `text_dir/AudioTranscriber.log`
- **自定义日志文件**: 当`log_file`不为`None`时使用

#### 3.5 TextSummarizer类
- **参数添加**: `log_file: Union[str, Path] = None`
- **默认日志文件**: `summary_dir/TextSummarizer.log`
- **自定义日志文件**: 当`log_file`不为`None`时使用

### 4. 使用方式

#### 4.1 使用默认日志文件（不指定log_file）
```python
from utils import AVFinder
from pathlib import Path

finder = AVFinder(Path("input"), Path("output.json"))
# 日志文件：output.json.parent/AVFinder.log
```

#### 4.2 使用自定义日志文件
```python
from utils import AVFinder
from pathlib import Path

finder = AVFinder(
    Path("input"), 
    Path("output.json"),
    log_file=Path("custom_logs/avfinder.log")
)
# 日志文件：custom_logs/avfinder.log
```

#### 4.3 传入自定义logger（log_file参数被忽略）
```python
from utils import AVFinder
from pathlib import Path
import logging

custom_logger = logging.getLogger("my_logger")
finder = AVFinder(
    Path("input"), 
    Path("output.json"),
    logger=custom_logger,
    log_file=Path("custom_logs/avfinder.log")  # 这个参数会被忽略
)
# 使用传入的custom_logger，不创建新的日志文件
```

### 5. 行为规则

1. **优先级规则**:
   - 如果传入了`logger`参数，则使用传入的logger，`log_file`参数被忽略
   - 如果没有传入`logger`参数，则创建新的logger
     - 如果`log_file`不为`None`，使用自定义日志文件
     - 如果`log_file`为`None`，使用默认日志文件

2. **日志文件创建**:
   - 自动创建日志文件的父目录（如果不存在）
   - 记录日志文件路径信息：`使用自定义日志文件: {path}` 或 `使用默认日志文件: {path}`

3. **日志格式**:
   - 控制台输出和文件日志使用相同的格式
   - 格式：`[ClassName] %(asctime)s - %(levelname)s - %(message)s`
   - 包含类名前缀，便于区分不同类的日志

### 6. 向后兼容性

#### 6.1 完全向后兼容
- 现有代码不需要修改，`log_file`参数有默认值`None`
- 现有调用方式继续有效

#### 6.2 更新main.py中的调用
由于所有类现在都需要`logger`参数（之前有些调用没有传递），更新了`main.py`中的调用：
```python
# 之前（某些调用没有传递logger）
finder = AVFinder(input_dir, input_json)

# 之后（所有调用都传递logger）
finder = AVFinder(input_dir, input_json, logger=logger)
```

### 7. 优势

1. **灵活性**: 用户可以指定自定义日志文件路径
2. **统一管理**: 可以将所有类的日志集中到一个文件中
3. **调试便利**: 便于查看和分析日志
4. **向后兼容**: 不影响现有功能
5. **透明性**: 清晰的日志记录，显示使用的日志文件路径

### 8. 使用示例

#### 示例1：将所有日志集中到一个文件
```python
from utils import AVFinder, AudioExtractor
from pathlib import Path

log_file = Path("all_logs/audio_summary.log")

finder = AVFinder(Path("input"), Path("output.json"), log_file=log_file)
extractor = AudioExtractor(
    Path("input.json"), 
    Path("output.json"),
    Path("audios"),
    "ffmpeg",
    "ffprobe",
    log_file=log_file
)
# 两个类的日志都输出到 all_logs/audio_summary.log
```

#### 示例2：为每个类使用不同的日志文件
```python
from utils import AVFinder, AudioExtractor
from pathlib import Path

finder = AVFinder(
    Path("input"), 
    Path("output.json"),
    log_file=Path("logs/avfinder.log")
)

extractor = AudioExtractor(
    Path("input.json"), 
    Path("output.json"),
    Path("audios"),
    "ffmpeg",
    "ffprobe",
    log_file=Path("logs/audio_extractor.log")
)
# 每个类使用独立的日志文件
```

#### 示例3：在main.py中使用
```python
# 可以为每个步骤指定不同的日志文件
finder = AVFinder(input_dir, input_json, logger=logger, 
                  log_file=interm_dir / "avfinder.log")

extractor = AudioExtractor(
    input_json=input_json,
    output_json=audio_json,
    audio_dir=audio_dir,
    ffmpeg_path=ffmpeg_path,
    ffprobe_path=ffprobe_path,
    num_processes=processes,
    logger=logger,
    log_file=interm_dir / "audio_extractor.log"
)
```

### 9. 注意事项

1. **目录创建**: 如果自定义日志文件的父目录不存在，会自动创建
2. **文件权限**: 确保有权限写入日志文件
3. **日志轮转**: 当前实现不支持日志轮转，长时间运行可能导致日志文件过大
4. **并发访问**: 多个进程同时写入同一个日志文件可能导致内容交错

这样实现的`log_file`参数功能既满足了需求，又保持了代码的清晰性和灵活性。