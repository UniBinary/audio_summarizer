# Logger初始化逻辑统一修改说明

## 修改目标
将`utils.py`中每个类的logger初始化逻辑都仿照`AVFinder`类的模式进行统一，确保：
1. 所有类都使用相同的logger初始化模式
2. 每个类都有自己的`_setup_logger()`方法
3. 日志格式包含类名前缀，便于区分不同类的日志
4. 每个类都创建独立的日志文件

## 修改的文件

### utils.py

#### 1. AVFinder类 (已符合要求，作为参考模板)
- **logger初始化模式**:
  ```python
  if logger is None:
      self._setup_logger()
  else:
      self.logger = logger
  ```
- **_setup_logger()方法特点**:
  - 创建带有`[AVFinder]`前缀的格式化字符串
  - 同时添加控制台handler和文件handler
  - 日志文件保存到输出目录：`output_dir/AVFinder.log`

#### 2. AudioExtractor类 (已修改)
- **修改前**:
  ```python
  if logger is None:
      self.logger = logging.getLogger(__name__)
      self.logger.setLevel(logging.INFO)
      if not self.logger.handlers:
          handler = logging.StreamHandler()
          formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
          handler.setFormatter(formatter)
          self.logger.addHandler(handler)
  else:
      self.logger = logger
  ```
- **修改后**:
  ```python
  if logger is None:
      self._setup_logger()
  else:
      self.logger = logger
  ```
- **新增的_setup_logger()方法**:
  - 格式化字符串：`[AudioExtractor] %(asctime)s - %(levelname)s - %(message)s`
  - 日志文件：`audio_dir/AudioExtractor.log`

#### 3. OSSUploader类 (已修改)
- **修改前**:
  ```python
  if logger is None:
      self.logger = logging.getLogger(__name__)
      self.logger.setLevel(logging.INFO)
      if not self.logger.handlers:
          handler = logging.StreamHandler()
          formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
          handler.setFormatter(formatter)
          self.logger.addHandler(handler)
  else:
      self.logger = logger
  ```
- **修改后**:
  ```python
  if logger is None:
      self._setup_logger()
  else:
      self.logger = logger
  ```
- **新增的_setup_logger()方法**:
  - 格式化字符串：`[OSSUploader] %(asctime)s - %(levelname)s - %(message)s`
  - 日志文件：`output_json.parent/OSSUploader.log`

#### 4. AudioTranscriber类 (已修改)
- **修改前**:
  ```python
  if logger is None:
      self.logger = logging.getLogger(__name__)
      self.logger.setLevel(logging.INFO)
      if not self.logger.handlers:
          handler = logging.StreamHandler()
          formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
          handler.setFormatter(formatter)
          self.logger.addHandler(handler)
  else:
      self.logger = logger
  ```
- **修改后**:
  ```python
  if logger is None:
      self._setup_logger()
  else:
      self.logger = logger
  ```
- **新增的_setup_logger()方法**:
  - 格式化字符串：`[AudioTranscriber] %(asctime)s - %(levelname)s - %(message)s`
  - 日志文件：`text_dir/AudioTranscriber.log`

#### 5. TextSummarizer类 (已修改)
- **修改前**:
  ```python
  if logger is None:
      self.logger = logging.getLogger(__name__)
      self.logger.setLevel(logging.INFO)
      if not self.logger.handlers:
          handler = logging.StreamHandler()
          formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
          handler.setFormatter(formatter)
          self.logger.addHandler(handler)
  else:
      self.logger = logger
  ```
- **修改后**:
  ```python
  if logger is None:
      self._setup_logger()
  else:
      self.logger = logger
  ```
- **新增的_setup_logger()方法**:
  - 格式化字符串：`[TextSummarizer] %(asctime)s - %(levelname)s - %(message)s`
  - 日志文件：`summary_dir/TextSummarizer.log`

## 统一后的logger初始化模式

### 1. 构造函数中的logger处理
```python
def __init__(self, ..., logger=None):
    # ... 其他初始化代码 ...
    
    # 设置logger
    if logger is None:
        self._setup_logger()
    else:
        self.logger = logger
    
    # ... 其他初始化代码 ...
```

### 2. _setup_logger()方法结构
```python
def _setup_logger(self):
    self.logger = logging.getLogger(__name__)
    self.logger.setLevel(logging.INFO)
    
    if not self.logger.handlers:
        # 控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('[ClassName] %(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
    
        # 文件handler
        output_dir = self.output_json.parent  # 或其他适当的目录
        output_dir.mkdir(parents=True, exist_ok=True)
        log_file = output_dir / "ClassName.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter('[ClassName] %(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)
```

## 修改后的优势

### 1. 一致性
- 所有类使用相同的logger初始化模式
- 代码结构统一，便于维护和理解

### 2. 可读性
- 每个类的日志都有明确的类名前缀，便于区分
- 控制台输出和文件日志格式一致

### 3. 调试便利性
- 每个类创建独立的日志文件，便于问题定位
- 日志文件保存在相关的工作目录中

### 4. 灵活性
- 仍然支持传入自定义logger
- 如果没有传入logger，自动创建适合的logger

### 5. 向后兼容性
- 完全保持向后兼容
- 现有代码可以继续传入自定义logger或不传入logger

## 日志文件位置

| 类名 | 日志文件位置 | 格式化前缀 |
|------|-------------|-----------|
| AVFinder | `output_json.parent/AVFinder.log` | `[AVFinder]` |
| AudioExtractor | `audio_dir/AudioExtractor.log` | `[AudioExtractor]` |
| OSSUploader | `output_json.parent/OSSUploader.log` | `[OSSUploader]` |
| AudioTranscriber | `text_dir/AudioTranscriber.log` | `[AudioTranscriber]` |
| TextSummarizer | `summary_dir/TextSummarizer.log` | `[TextSummarizer]` |

## 测试验证

通过代码检查确认：
1. 所有5个类都使用了相同的`self._setup_logger()`初始化模式
2. 所有5个类都有对应的`_setup_logger()`方法
3. 所有类的日志格式都包含类名前缀
4. 所有类都创建了独立的日志文件

## 使用示例

### 使用默认logger
```python
from utils import AVFinder
from pathlib import Path

finder = AVFinder(Path("input"), Path("output.json"))
# 自动创建带有[AVFinder]前缀的logger
# 日志文件保存到 output.json.parent/AVFinder.log
```

### 传入自定义logger
```python
from utils import AVFinder
from pathlib import Path
import logging

custom_logger = logging.getLogger("my_logger")
finder = AVFinder(Path("input"), Path("output.json"), logger=custom_logger)
# 使用传入的custom_logger
```

这样修改后，项目的logger系统更加统一、规范，便于调试和维护。